"""運用（G1 / API-80, API-81）: チェーン連携ワーカーのジョブ（chain_jobs）の一覧と、失敗ジョブの再投入。
運用者（OPS_ADDRESSES のウォレット。未設定なら DEV_LOGIN_ENABLED のときだけ全員）だけが使える。
payload のうち表示に使う ID と金額だけを返し、署名・秘密鍵・text record の本文は返さない。"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from ..auth import ops_user
from ..db import get_db
from ..models import Agent, Case, ChainJob, Task, User
from ..config import get_settings
from ..services import chain, worker

router = APIRouter(prefix="/ops", tags=["ops"])

KIND_LABEL = {
    "fund_task": "Step deposit (fundTask)", "submit": "Submit Deliverable (submit)", "approve": "Relay Approval (approve)", "dispute": "Send back (dispute)",
    "resolve": "Apply ruling (resolve)", "ens_publish": "Publish Agent to ENS", "ens_update": "Update ENS records", "ens_project": "Issue Case subname", "ens_subagents": "Sync specialist agents to ENS",
}
# 再投入できるのは failed だけ。retry はワーカーが自動で拾うので、ここから触るとワーカーと競合する
RETRYABLE = {"failed"}
_STATUS_PRIORITY = {"failed": 0, "retry": 1, "running": 2, "queued": 3, "done": 4}
# オンチェーンの工程状態の順序。再投入前に「既に反映済み」を判定する
_TASK_ORDER = {"none": 0, "funded": 1, "submitted": 2, "paid": 3, "disputed": 3, "resolved": 4}
_TARGET_STATUS = {"fund_task": "funded", "submit": "submitted", "dispute": "disputed", "resolve": "resolved"}


class ChainJobOut(BaseModel):
    id: str
    kind: str
    label: str
    idempotency_key: str
    status: str
    attempts: int
    max_attempts: int
    tx_hash: str | None
    error: str | None
    next_attempt_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    updated_at: datetime
    # payload から表示用に抜いたもの
    case_id: str | None = None
    case_title: str | None = None
    task_id: str | None = None
    task_title: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    amount: str | None = None
    href: str | None = None  # 画面上のリンク先
    retryable: bool


class OpsJobsOut(BaseModel):
    counts: dict[str, int]  # status -> 件数（フィルタ前の全体）
    kinds: list[str]
    worker_alive: bool
    jobs: list[ChainJobOut]


def _to_out(db: Session, j: ChainJob, cache: dict) -> ChainJobOut:
    p = j.payload or {}
    o = ChainJobOut(id=j.id, kind=j.kind, label=KIND_LABEL.get(j.kind, j.kind), idempotency_key=j.idempotency_key, status=j.status, attempts=j.attempts,
                    max_attempts=worker.MAX_ATTEMPTS, tx_hash=j.tx_hash, error=j.error, next_attempt_at=j.next_attempt_at, finished_at=j.finished_at,
                    created_at=j.created_at, updated_at=j.updated_at, amount=p.get("amount") or p.get("pay_amount"), retryable=j.status in RETRYABLE)
    task_id = p.get("task_db_id")
    case_id = p.get("case_db_id")
    agent_id = p.get("agent_id")
    if task_id:
        t = cache.setdefault(("task", task_id), db.get(Task, task_id))
        if t is not None:
            o.task_id, o.task_title, case_id = t.id, t.title, t.case_id
    if case_id:
        c = cache.setdefault(("case", case_id), db.get(Case, case_id))
        if c is not None:
            o.case_id, o.case_title, o.href = c.id, c.title, f"/cases/{c.id}/audit"
    if agent_id:
        a = cache.setdefault(("agent", agent_id), db.get(Agent, agent_id))
        if a is not None:
            o.agent_id, o.agent_name, o.href = a.id, a.name, f"/agents/{a.id}"
    return o


@router.get("/jobs", response_model=OpsJobsOut)
def list_jobs(status: str | None = Query(default=None), kind: str | None = Query(default=None), limit: int = Query(default=100, ge=1, le=500),
              _: User = Depends(ops_user), db: Session = Depends(get_db)):
    counts = {s: 0 for s in ("queued", "running", "retry", "done", "failed")}
    for s, n in db.query(ChainJob.status, func.count(ChainJob.id)).group_by(ChainJob.status).all():
        counts[s] = n
    kinds = [k for (k,) in db.query(ChainJob.kind).distinct().order_by(ChainJob.kind).all()]
    q = db.query(ChainJob)
    if status:
        q = q.filter(ChainJob.status.in_([s for s in status.split(",") if s]))
    if kind:
        q = q.filter(ChainJob.kind == kind)
    # 失敗・再送待ち・処理中を先頭に、あとは新しい順。limit より古い失敗ジョブが一覧から消えないよう、並び替えは SQL 側で行う
    priority = case(_STATUS_PRIORITY, value=ChainJob.status, else_=9)
    rows = q.order_by(priority, ChainJob.created_at.desc()).limit(limit).all()
    cache: dict = {}
    return OpsJobsOut(counts=counts, kinds=kinds, worker_alive=worker.is_alive(), jobs=[_to_out(db, j, cache) for j in rows])


def _already_on_chain(j: ChainJob) -> str | None:
    """Escrow 系のジョブについて、オンチェーンの工程状態が既にこのジョブの結果以降なら理由を返す（再送すると revert か二重実行になる）。
    tx が送信されたあと受信確認だけがタイムアウトして failed になった場合がこれに当たる。モック時・ENS 系・読み取り失敗は None（判定しない）。"""
    target = _TARGET_STATUS.get(j.kind)
    p = j.payload or {}
    if not target or not get_settings().chain_enabled or not p.get("case_id_hex") or not p.get("task_id_hex"):
        return None
    try:
        on = chain.read_task(p["case_id_hex"], p["task_id_hex"])
    except Exception:  # noqa: BLE001
        return None
    if not on:
        return None
    cur = on.get("status", "none")
    if j.kind == "submit" and cur == "submitted" and on.get("deliverable_hash", "").lower() != (p.get("deliverable_hash") or "").lower():
        return None  # 別の成果物が提出済み → 再提出は正当
    if _TASK_ORDER.get(cur, 0) >= _TASK_ORDER[target]:
        return f"The on-chain Step is already {cur} (the tx was likely sent and only the receipt check failed). Do not resend; use \"Resync\" on the Case details page to refresh the projection"
    return None


@router.post("/jobs/{job_id}/retry", response_model=ChainJobOut)
def retry_job(job_id: str, _: User = Depends(ops_user), db: Session = Depends(get_db)):
    """failed（自動再送 5 回を使い切った）ジョブを、待ち時間なしで再投入する。試行回数は 0 に戻す（再び最大 5 回）。
    冪等キーはジョブの二重登録を防ぐだけで、再投入は新しい tx を送る。そのため Escrow 系は再送前にオンチェーンの状態を確認し、
    既に反映済みなら 409 で断る。状態の更新は failed のときだけ通る UPDATE で行い、ワーカーとの競合を防ぐ。ens_publish は Agent を publishing に戻す。"""
    j = db.get(ChainJob, job_id)
    if j is None:
        raise HTTPException(404, "Job not found")
    if j.status not in RETRYABLE:
        raise HTTPException(409, f"Only failed Jobs can be requeued (currently {j.status}; the worker resends retry Jobs automatically)")
    reason = _already_on_chain(j)
    if reason:
        raise HTTPException(409, reason)
    note = f" [requeued by operator {datetime.now(UTC).isoformat(timespec='seconds')}]"
    err = ((j.error or "")[:1800] + note) if j.error else note.strip()
    n = (db.query(ChainJob).filter(ChainJob.id == j.id, ChainJob.status == "failed")
         .update({"status": "retry", "attempts": 0, "next_attempt_at": None, "finished_at": None, "error": err}, synchronize_session=False))
    if n != 1:
        db.rollback()
        raise HTTPException(409, "The Job status has changed. Please reload")
    if j.kind == "ens_publish":
        a = db.get(Agent, (j.payload or {}).get("agent_id", ""))
        if a is not None and a.status == "publish_failed":
            a.status, a.ens_error = "publishing", None
    db.commit()
    db.refresh(j)
    worker.wake()
    return _to_out(db, j, {})
