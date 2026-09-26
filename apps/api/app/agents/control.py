"""キルスイッチ（WP-007 / GRD-007・agent-infra 12-1・OPS-001〜003）。
全体と案件単位の 2 段階でエージェントの実行を止める。止まっている間は新規の委譲を受け付けず、
実行中のものは次のツール呼び出しの前に中断する（tools.call_tool が確かめる）。
操作は agent_controls に 1 行ずつ積み上げ、範囲ごとの最新の行を現在の状態とする（操作の記録を兼ねる）。
公開 API には出さず、管理用スクリプト scripts/agent_ops.py から操作する（DEC-010）。"""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ..models import AgentControl, AgentRun, Dispute
from .trace import redact

GLOBAL = "global"


class AgentStopped(Exception):
    """停止中に委譲やツール呼び出しをしようとしたときに投げる（ensure_running）。"""


@dataclass
class StopState:
    stopped: bool
    scope: str | None = None  # 止めている範囲（global / case:<ID>）
    reason: str = ""


def case_scope(case_id: str) -> str:
    return f"case:{case_id}"


def _record(db: Session, scope: str, action: str, reason: str, operator: str) -> AgentControl:
    row = AgentControl(scope=scope, action=action, reason=redact(reason)[:1000], operator=operator[:120])
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def stop(db: Session, *, case_id: str | None = None, reason: str, operator: str) -> AgentControl:
    """OPS-001（case_id なし）/ OPS-002（case_id あり）。"""
    if not reason.strip():
        raise ValueError("停止の理由を書いてください（OPS-001 / OPS-002 の記録に残す）")
    return _record(db, case_scope(case_id) if case_id else GLOBAL, "stop", reason, operator)


def resume(db: Session, *, case_id: str | None = None, reason: str, operator: str) -> AgentControl:
    """OPS-003。全体の再開は案件単位の停止を解かない（範囲ごとに独立）。"""
    return _record(db, case_scope(case_id) if case_id else GLOBAL, "resume", reason, operator)


def _latest(db: Session, scope: str) -> AgentControl | None:
    return (db.query(AgentControl).filter(AgentControl.scope == scope)
            .order_by(AgentControl.created_at.desc(), AgentControl.id.desc()).first())


def state(db: Session, case_id: str | None = None) -> StopState:
    """全体の停止を先に、次に案件の停止を見る。"""
    scopes = [GLOBAL] + ([case_scope(case_id)] if case_id else [])
    for scope in scopes:
        row = _latest(db, scope)
        if row is not None and row.action == "stop":
            return StopState(True, scope, row.reason)
    return StopState(False)


def case_of_run(db: Session, run: AgentRun) -> str | None:
    """実行が結び付いた案件（紛争の実行なら、その紛争の案件）。"""
    if run.case_id:
        return run.case_id
    if run.dispute_id:
        d = db.get(Dispute, run.dispute_id)
        return d.case_id if d else None
    return None


def state_for_run(db: Session, run: AgentRun) -> StopState:
    return state(db, case_of_run(db, run))


def ensure_running(db: Session, case_id: str | None = None) -> None:
    """委譲を始める前に呼ぶ。止まっていれば AgentStopped。"""
    s = state(db, case_id)
    if s.stopped:
        raise AgentStopped(f"停止中です（{s.scope}: {s.reason}）")


def stopped_scopes(db: Session) -> list[AgentControl]:
    """いま止まっている範囲（各範囲の最新の行が stop のもの）。"""
    scopes = [s for (s,) in db.query(AgentControl.scope).distinct()]
    rows = [_latest(db, s) for s in scopes]
    return sorted((r for r in rows if r is not None and r.action == "stop"), key=lambda r: r.scope)
