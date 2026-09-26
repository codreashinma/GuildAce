"""エージェントの実行のランナー（WP-017 / DEC-008 (b)・INF-006・agent-orchestration 10 章・agent-infra 4〜5 章）。
AG-001 の実行を agent_runs のジョブ行（status = queued）で受け付け、API プロセス内の 1 本のスレッドが古い順に 1 件ずつ実行する
（既存のチェーン連携ワーカー services/worker.py と同じ方式）。
- 1 案件 1 実行: 同じ案件・紛争・モードの待ち・実行中があれば受け付けない（agent_runs の部分一意索引。trace.enqueue_run）
- 停止中（GRD-007）の案件の実行は取り出さない。待ちのまま残し、再開後に取り出す
- 起動時、実行中のまま残った AG-001 の実行を待ちに戻す（recover_stale）。保存は版で冪等なので、やり直しても版は増えない（10 章）
  委譲先（AG-002〜004）の実行中のまま残った行は、中断として failed にする（再開では AG-001 が委譲し直す）
- 計画が正常に終わったら、結果を tasks に写して HIL-002（awaiting_approval）へつなぐ（WP-018。apply_plan）
- 紛争の論点整理は、成否にかかわらず結果（論点なしを含む）を disputes.summary_json に写す（WP-019。apply_dispute。HIL-004 を止めない）
実行の受け付け（request_planning / request_dispute）は run_queue に置く（ルータから呼ぶため。循環 import を避ける）。"""

import logging
import threading
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import AgentRun
from . import ag001_orchestrator, apply_dispute, apply_plan, control, run_queue, trace
from .run_queue import request_dispute, request_planning  # noqa: F401  既存の呼び方（runner.request_planning）を保つ

log = logging.getLogger(__name__)
MODES = ("plan", "analyze_dispute")


def claim_next(db: Session) -> AgentRun | None:
    """停止されていない案件の待ちのうち、いちばん古いものを実行中にして返す。"""
    queued = (db.query(AgentRun).filter(AgentRun.agent_id == "AG-001", AgentRun.status == "queued")
              .order_by(AgentRun.created_at, AgentRun.id).all())
    for run in queued:
        if control.state_for_run(db, run).stopped:  # GRD-007: 止まっている案件は取り出さない
            continue
        # 実行の時間上限（11 章）は取り出した時点から数える。待っていた時間は含めない
        run.status, run.started_at, run.finished_at = "running", datetime.now(UTC), None
        db.commit()
        return run
    return None


def execute(db: Session, run: AgentRun) -> None:
    """取り出した実行を AG-001 で進める。例外が出たら failed にして記録する（次の実行は止めない）。"""
    try:
        if run.mode == "plan":
            result = ag001_orchestrator.run_planning(db, case_id=run.case_id, run=run)
            if result.ok:  # WP-018: tasks に写して HIL-002 へ
                apply_plan.apply(db, run)
        elif run.mode == "analyze_dispute":
            result = ag001_orchestrator.run_dispute(db, dispute_id=run.dispute_id, run=run)
            apply_dispute.apply(db, run, None if result.ok else result.reason)  # WP-019: 論点なしでも写す
        else:
            trace.finish_run(db, run, "failed", error=f"未知のモード: {run.mode}")
    except Exception as e:  # noqa: BLE001
        log.exception("agent run failed: %s", run.id)
        db.rollback()
        if run.status == "running":
            trace.finish_run(db, run, "failed", error=f"{type(e).__name__}: {e}")
        if run.mode == "analyze_dispute":  # 例外でも Jury の画面を「整理中」のままにしない（HIL-004 を止めない）
            apply_dispute.apply(db, run, "error")


def process_once(db: Session) -> bool:
    """待ちの実行を 1 件処理する。処理したら True。"""
    run = claim_next(db)
    if run is None:
        return False
    execute(db, run)
    return True


def recover_stale(db: Session) -> int:
    """前回のプロセスが実行中のまま落ちた実行を戻す。AG-001 は待ちへ、委譲先は failed（中断）へ。戻した AG-001 の件数を返す。"""
    stale = db.query(AgentRun).filter(AgentRun.status == "running").all()
    resumed = 0
    for run in stale:
        if run.agent_id == "AG-001" and run.mode in MODES:
            run.status = "queued"
            run.error = ((run.error or "") + " [前回のプロセス終了時に実行中だったため再実行]").strip()
            resumed += 1
        else:
            run.status, run.finished_at = "failed", datetime.now(UTC)
            run.error = ((run.error or "") + " [前回のプロセス終了時に中断]").strip()
    if stale:
        db.commit()
        log.warning("agent runner: 実行中のまま残っていた実行 %d 件のうち %d 件を再実行します", len(stale), resumed)
    return resumed


def _loop() -> None:
    while True:
        db = SessionLocal()
        try:
            while process_once(db):
                pass
        except Exception:  # noqa: BLE001
            log.exception("agent runner loop error")
        finally:
            db.close()
        run_queue.wait(timeout=3)


def start() -> None:
    db = SessionLocal()
    try:
        recover_stale(db)
    finally:
        db.close()
    threading.Thread(target=_loop, name="agent-runner", daemon=True).start()
