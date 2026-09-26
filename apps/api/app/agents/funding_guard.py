"""送金のガード（WP-020 / GRD-009・GRD-010・GRD-011・GRD-007・OPS-001 の権限の失効）。
TOOL-009（WP-021）が送金の要求を受理する前に、決定的なコードで判定する。モデルの出力は一切使わない。
- 入力は task_id と revision（冪等キー。HIL-002 で承諾されたチーム案の版）だけ。金額と送金先は引数に取らない
- 金額と送金先（Escrow の案件・タスク）は tasks から読む（GRD-009 (1)）
- 判定: 承諾済み（GRD-011）・権限が有効（GRD-010）・1 タスク 1 回と 24 時間の上限（GRD-009 (2)）・停止中でない（GRD-007）
- 満たさない条件はすべて理由として返す。受理でも送金のジョブは投入しない（WP-021 の役目）
権限（funding_grants）は案件単位で発行し、発行から funding_grant_days、案件の completed / resolved、停止の操作で失効する。"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import Case, ChainJob, FundingGrant, Task
from . import control

FUND_JOB = "fund_task"  # 送金のジョブの種類（services/worker.py）
APPROVED_STATUSES = ("in_progress", "delivered", "disputed")  # HIL-002 の承諾（openCase の確認）より後
SETTLED_STATUSES = ("completed", "resolved")  # 設計の settled（計画 3 章）。cancelled は実装に無い


@dataclass
class FundingOrder:
    """受理した送金の中身。すべて tasks から読んだ値（GRD-009 (1)）"""
    task_db_id: str
    case_id_hex: str
    task_id_hex: str
    amount: int  # USDC の最小単位


@dataclass
class FundingDecision:
    ok: bool
    reasons: list[str] = field(default_factory=list)  # 満たさなかった条件（GRD の ID を先頭に付ける）
    order: FundingOrder | None = None


def _now() -> datetime:
    return datetime.now(UTC)


def _aware(t: datetime) -> datetime:
    return t if t.tzinfo else t.replace(tzinfo=UTC)


# ---------------------------------------------------------------- 権限（GRD-010）


def issue(db: Session, case_id: str) -> FundingGrant:
    """案件の送金操作権限を発行する（WP-021 で /opened の承諾の確認のあとに呼ぶ）。有効な権限があればそれを返す。"""
    grant = active_grant(db, case_id)
    if grant is not None:
        return grant
    now = _now()
    grant = FundingGrant(case_id=case_id, issued_at=now, expires_at=now + timedelta(days=get_settings().funding_grant_days))
    db.add(grant)
    db.commit()
    return grant


def active_grant(db: Session, case_id: str) -> FundingGrant | None:
    """失効していない権限（取り消されておらず、期限内で、案件が完了していない）"""
    case = db.get(Case, case_id)
    if case is None or case.status in SETTLED_STATUSES:
        return None
    now = _now()
    for g in db.query(FundingGrant).filter(FundingGrant.case_id == case_id, FundingGrant.revoked_at.is_(None)):
        if _aware(g.expires_at) > now:
            return g
    return None


def revoke(db: Session, *, case_id: str | None = None, reason: str) -> int:
    """権限を即時に失効させる（OPS-001: case_id なし = 全案件 / OPS-002: 案件単位）。失効させた件数を返す。
    すでに投入された送金のジョブは取り消さない（チェーンへ送った tx は取り消せない）。"""
    q = db.query(FundingGrant).filter(FundingGrant.revoked_at.is_(None))
    if case_id:
        q = q.filter(FundingGrant.case_id == case_id)
    rows = q.all()
    now = _now()
    for g in rows:
        g.revoked_at, g.revoke_reason = now, reason[:1000]
    db.commit()
    return len(rows)


# ---------------------------------------------------------------- 判定


def _funded_before(db: Session, task: Task) -> bool:
    """このタスクの送金がすでにある（投影が none でない、または失敗以外の送金のジョブがある）"""
    if task.chain_status != "none":
        return True
    jobs = db.query(ChainJob).filter(ChainJob.kind == FUND_JOB, ChainJob.status != "failed").all()
    return any(j.payload.get("task_db_id") == task.id for j in jobs)


def sent_in_24h(db: Session) -> int:
    """直近 24 時間に投入された送金の合計（失敗したジョブを除く）。運用ウォレットは 1 つ（SERVER_PRIVATE_KEY）"""
    since = _now() - timedelta(hours=24)
    jobs = db.query(ChainJob).filter(ChainJob.kind == FUND_JOB, ChainJob.status != "failed", ChainJob.created_at >= since).all()
    return sum(int(j.payload.get("amount", 0)) for j in jobs)


def check(db: Session, task_id: str, revision: int) -> FundingDecision:
    """送金の要求を受理してよいか。金額と送金先は引数に無く、tasks から読む。"""
    task = db.get(Task, task_id, populate_existing=True)
    if task is None:
        return FundingDecision(False, ["GRD-009: Task not found"])
    case = db.get(Case, task.case_id, populate_existing=True)
    reasons: list[str] = []

    # GRD-009 (1): 送金の中身はすべて tasks と承諾済みのチーム案から
    approved_revision = (case.plan_json or {}).get("team_proposal_revision")
    if approved_revision is None or revision != approved_revision:
        reasons.append("GRD-009: The revision does not match the accepted team proposal")
    if not task.escrow_task_id or not case.escrow_case_id:
        reasons.append("GRD-009: The Escrow task has not been determined")
    amount = int(task.estimated_cost)

    # GRD-011: HIL-002 で承諾済み（openCase が確認され、承諾より後の状態）
    if not case.open_tx_hash or case.status not in (*APPROVED_STATUSES, *SETTLED_STATUSES):
        reasons.append("GRD-011: The case has not been accepted")

    # GRD-010: 権限が失効していない
    if active_grant(db, case.id) is None:
        reasons.append("GRD-010: No transfer permission (not issued, expired, stopped, or case completed)")

    # GRD-009 (2): 1 タスク 1 回、直近 24 時間の上限
    if _funded_before(db, task):
        reasons.append("GRD-009: This task has already been funded (once per task)")
    limit = get_settings().funding_limit_24h
    if sent_in_24h(db) + amount > limit:
        reasons.append(f"GRD-009: Exceeds the transfer limit for the last 24 hours (limit: {limit})")

    # GRD-007: 停止中でない
    s = control.state(db, case.id)
    if s.stopped:
        reasons.append(f"GRD-007: Stopped ({s.scope})")

    if reasons:
        return FundingDecision(False, reasons)
    return FundingDecision(True, [], FundingOrder(task_db_id=task.id, case_id_hex=case.escrow_case_id,
                                                  task_id_hex=task.escrow_task_id, amount=amount))
