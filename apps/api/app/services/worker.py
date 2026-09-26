"""チェーン連携ワーカー（CMP-009 / ADR-006）。
オンチェーン（Escrow）と ENS への書き込みはすべてここを通る。
- サービス層はジョブを投入するだけ（非同期）。冪等キーで二重投入を防ぐ
- ワーカーは 1 スレッドで順に送信する（運用ウォレットの nonce 競合を避ける）。失敗は再送する
- 確定した tx のイベントを読み、DB の投影（tasks.chain_status 等）を更新する。モック時は送信せずに投影だけ更新する"""

import logging
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import SessionLocal
from ..models import ChainJob
from . import chain, ens

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5
_wake = threading.Event()


def enqueue(db: Session, kind: str, key: str, payload: dict[str, Any]) -> ChainJob | None:
    """ジョブを投入する。同じ冪等キーのジョブが既にあれば投入しない。"""
    job = ChainJob(kind=kind, idempotency_key=key, payload=payload, status="queued")
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return None
    _wake.set()
    return job


def _send(w, fn) -> str:
    s = get_settings()
    from eth_account import Account

    acct = Account.from_key(s.server_private_key)
    tx = fn.build_transaction({"from": acct.address, "nonce": w.eth.get_transaction_count(acct.address, "pending"), "chainId": s.chain_id})
    h = w.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    receipt = w.eth.wait_for_transaction_receipt(h, timeout=240)
    if receipt["status"] != 1:
        raise RuntimeError(f"tx reverted: {h.to_0x_hex()}")
    return h.to_0x_hex()


# ------------------------------------------------------------------ handlers
# 各ハンドラは (tx_hash, projection) を返す。projection は DB 反映用の辞書。


def _h(x: str) -> bytes:
    return bytes.fromhex(x[2:])


def _fund_task(p: dict) -> tuple[str, dict]:
    if not get_settings().chain_enabled:
        return chain.mock_tx_hash(), {"chain_status": "funded"}
    w = chain.w3()
    tx = _send(w, chain.escrow(w).functions.fundTask(_h(p["case_id_hex"]), _h(p["task_id_hex"]), int(p["amount"])))
    return tx, {"chain_status": "funded"}


def _submit(p: dict) -> tuple[str, dict]:
    if not get_settings().chain_enabled:
        return chain.mock_tx_hash(), {"chain_status": "submitted", "approval_count": 0}
    w = chain.w3()
    from web3 import Web3

    tx = _send(w, chain.escrow(w).functions.submit(_h(p["case_id_hex"]), _h(p["task_id_hex"]), _h(p["deliverable_hash"]), Web3.to_checksum_address(p["payee"])))
    return tx, {"chain_status": "submitted", "approval_count": 0}


def _approve(p: dict) -> tuple[str, dict]:
    if not get_settings().chain_enabled:
        count = int(p.get("approval_count_after", 1))
        paid = count >= int(p.get("threshold", 1))
        return chain.mock_tx_hash(), {"chain_status": "paid" if paid else "submitted", "approval_count": count}
    w = chain.w3()
    from web3 import Web3

    esc = chain.escrow(w)
    tx = _send(w, esc.functions.approve(_h(p["case_id_hex"]), _h(p["task_id_hex"]), _h(p["deliverable_hash"]), Web3.to_checksum_address(p["payee"]), Web3.to_checksum_address(p["approver"]), _h(p["signature"])))
    t = chain.read_task(p["case_id_hex"], p["task_id_hex"]) or {}
    return tx, {"chain_status": t.get("status", "submitted"), "approval_count": t.get("approval_count", 0)}


def _dispute(p: dict) -> tuple[str, dict]:
    if not get_settings().chain_enabled:
        return chain.mock_tx_hash(), {"chain_status": "disputed"}
    w = chain.w3()
    tx = _send(w, chain.escrow(w).functions.dispute(_h(p["case_id_hex"]), _h(p["task_id_hex"])))
    return tx, {"chain_status": "disputed"}


def _resolve(p: dict) -> tuple[str, dict]:
    if not get_settings().chain_enabled:
        return chain.mock_tx_hash(), {"chain_status": "resolved"}
    w = chain.w3()
    tx = _send(w, chain.escrow(w).functions.resolve(_h(p["case_id_hex"]), _h(p["task_id_hex"]), int(p["pay_amount"]), int(p["refund_amount"])))
    return tx, {"chain_status": "resolved"}


def _ens_publish(p: dict) -> tuple[str, dict]:
    name, tx = ens.publish_agent(label=p["label"], payout_address=p["payout_address"], texts=p["texts"])
    sub = None
    if get_settings().ens_write_enabled:
        try:
            sub = ens._subregistry(ens._w3()).functions.getSubregistry(p["label"]).call()
        except Exception:  # noqa: BLE001
            sub = None
    return tx, {"ens_name": name, "ens_subregistry": sub}


def _ens_update(p: dict) -> tuple[str, dict]:
    tx = ens.update_texts(p["label"], p["texts"], agent_name=p.get("agent_name")) or chain.mock_tx_hash()
    return tx, {}


def _ens_project(p: dict) -> tuple[str, dict]:
    if p.get("agent_mock"):
        # Agent がモック公開（ENS 上に無い）なら project subname もモック
        return chain.mock_tx_hash(), {"project_ens_name": f"{p['project_label']}.{p.get('agent_name') or ens.agent_ens_name(p['agent_label'])}"}
    name, tx = ens.publish_project(agent_label=p["agent_label"], project_label=p["project_label"], texts=p["texts"], agent_name=p.get("agent_name"))
    return tx, {"project_ens_name": name}


HANDLERS = {"fund_task": _fund_task, "submit": _submit, "approve": _approve, "dispute": _dispute, "resolve": _resolve,
            "ens_publish": _ens_publish, "ens_update": _ens_update, "ens_project": _ens_project}


# ------------------------------------------------------------------ projection


def _apply(db: Session, job: ChainJob, tx: str, proj: dict) -> None:
    """確定した結果を DB の投影に反映する。"""
    from ..models import Agent, Case, Task
    from ..routers.cases import after_chain_update

    p = job.payload
    if job.kind in ("fund_task", "submit", "approve", "dispute", "resolve"):
        t = db.get(Task, p["task_db_id"])
        if t is not None:
            for k, v in proj.items():
                setattr(t, k, v)
            t.chain_tx_hash = tx
            db.commit()
            after_chain_update(db, t.case_id)
    elif job.kind == "ens_publish":
        a = db.get(Agent, p["agent_id"])
        if a is not None:
            a.ens_name, a.ens_tx_hash, a.status, a.ens_error = proj["ens_name"], tx, "published", None
            if proj.get("ens_subregistry"):
                a.ens_subregistry = proj["ens_subregistry"]
            db.commit()
    elif job.kind == "ens_project":
        c = db.get(Case, p["case_db_id"])
        if c is not None:
            c.project_ens_name, c.project_ens_tx_hash = proj["project_ens_name"], tx
            db.commit()


def _fail(db: Session, job: ChainJob, err: str) -> None:
    from ..models import Agent

    if job.kind == "ens_publish":
        a = db.get(Agent, job.payload["agent_id"])
        if a is not None:
            a.status, a.ens_error = "publish_failed", err[:1000]
            db.commit()


def process_once(db: Session) -> bool:
    """queued なジョブを 1 件処理する。処理したら True。"""
    now = datetime.now(UTC)
    job = (
        db.query(ChainJob)
        .filter(ChainJob.status.in_(["queued", "retry"]), (ChainJob.next_attempt_at.is_(None)) | (ChainJob.next_attempt_at <= now))
        .order_by(ChainJob.created_at)
        .first()
    )
    if job is None:
        return False
    job.status, job.attempts = "running", job.attempts + 1
    db.commit()
    try:
        tx, proj = HANDLERS[job.kind](job.payload)
        job.status, job.tx_hash, job.error, job.finished_at = "done", tx, None, datetime.now(UTC)
        db.commit()
        _apply(db, job, tx, proj)
        log.info("chain job done: %s %s tx=%s", job.kind, job.idempotency_key, tx[:12])
    except Exception as e:  # noqa: BLE001
        log.exception("chain job failed: %s", job.kind)
        job.error = str(e)[:2000]
        job.status = "retry" if job.attempts < MAX_ATTEMPTS else "failed"
        job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=min(5 * 2 ** job.attempts, 120))  # 他のジョブを先に進める
        db.commit()
        if job.status == "failed":
            _fail(db, job, job.error)
    return True


def _loop() -> None:
    while True:
        db = SessionLocal()
        try:
            while process_once(db):
                pass
        except Exception:  # noqa: BLE001
            log.exception("worker loop error")
        finally:
            db.close()
        _wake.wait(timeout=3)
        _wake.clear()


def recover_stale(db: Session) -> int:
    """前回のプロセスが処理中（running）のまま落ちたジョブを retry に戻す（ワーカーは単一プロセス前提）。
    そのままだと二度と拾われず、Agent が publishing のまま止まる。"""
    stale = db.query(ChainJob).filter(ChainJob.status == "running").all()
    for j in stale:
        j.status, j.next_attempt_at, j.error = "retry", None, (j.error or "") + " [前回のプロセス終了時に処理中だったため再実行]"
    if stale:
        db.commit()
        log.warning("chain worker: 処理中のまま残っていたジョブ %d 件を再実行します", len(stale))
    return len(stale)


def start() -> None:
    db = SessionLocal()
    try:
        recover_stale(db)
    finally:
        db.close()
    threading.Thread(target=_loop, name="chain-worker", daemon=True).start()
