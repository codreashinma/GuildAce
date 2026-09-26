"""コスト・反復・時間・件数の上限（WP-008 / GRD-003・GRD-004・GRD-005、agent-orchestration 11 章）。
判定はモデルではなくこのモジュールの決定的なコードで行う。数値はすべて設定値（既定値は DEC-004。設計上は仮の値）。
- 反復・時間（11 章）: 1 回の実行（agent_runs の 1 行）の LLM 呼び出し回数と経過時間
- GRD-005: 案件あたりと全体（1 日）の累計トークン数。agent_runs の input_tokens + output_tokens を集計する
  強制する場所は設計では INF-009（エグレス側）だが、アプリ内の LLM 呼び出しの共通層で行う（DEC-010）
- GRD-003 / GRD-004: 件数の上限。数える対象（TOOL-004 の出力・TOOL-008 の呼び出し）を持つ WP から呼ぶ
打ち切った後のエスカレーション先（HIL-005 など、12-3）はここでは決めない（WP-015）。"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Literal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AgentRun, Dispute

log = logging.getLogger(__name__)

LimitKind = Literal["iterations", "time", "cost_case", "cost_global", "tasks", "reconfirms"]
WARN_RATIO = 0.8  # 上限の 80 % でログに警告を出す（agent-infra 8-3 のアラートの代わり）


@dataclass
class LimitHit:
    """上限に達したことと、その理由（呼び出し側がエスカレーション先を決める材料）。"""
    kind: LimitKind
    used: float
    limit: float
    scope: str = ""  # run:<ID> / case:<ID> / global

    @property
    def detail(self) -> str:
        return f"{self.kind} の上限に達しました（{self.scope}: {self.used:g} / {self.limit:g}）"


def max_iterations(agent_id: str) -> int:
    s = get_settings()
    return {"AG-001": s.agent_max_iterations_ag001, "AG-002": s.agent_max_iterations_ag002,
            "AG-003": s.agent_max_iterations_ag003, "AG-004": s.agent_max_iterations_ag004}[agent_id]


def run_time_limit_s(agent_id: str) -> float:
    s = get_settings()
    return float({"AG-001": s.agent_time_limit_ag001_s, "AG-002": s.agent_time_limit_ag002_s,
                  "AG-003": s.agent_time_limit_ag003_s, "AG-004": s.agent_time_limit_ag004_s}[agent_id])


def elapsed_s(run: AgentRun, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    started = run.started_at if run.started_at.tzinfo else run.started_at.replace(tzinfo=UTC)
    return max(0.0, (now - started).total_seconds())


def remaining_s(run: AgentRun, now: datetime | None = None) -> float:
    return max(0.0, run_time_limit_s(run.agent_id) - elapsed_s(run, now))


# ---------------------------------------------------------------- 11 章: 反復・時間


def check_run(run: AgentRun, now: datetime | None = None) -> LimitHit | None:
    """次の LLM 呼び出しの前に呼ぶ。反復の上限（呼び出し済みの回数）か時間の上限に達していれば LimitHit。"""
    scope = f"run:{run.id}"
    cap = max_iterations(run.agent_id)
    if run.iterations >= cap:
        return LimitHit("iterations", run.iterations, cap, scope)
    spent, cap_s = elapsed_s(run, now), run_time_limit_s(run.agent_id)
    if spent >= cap_s:
        return LimitHit("time", round(spent, 1), cap_s, scope)
    return None


# ---------------------------------------------------------------- GRD-005: トークン数


def _tokens():
    return func.coalesce(func.sum(AgentRun.input_tokens + AgentRun.output_tokens), 0)


def case_tokens(db: Session, case_id: str) -> int:
    """案件に結び付いた実行（紛争の実行を含む）の累計トークン数。"""
    disputes = select(Dispute.id).where(Dispute.case_id == case_id)
    q = select(_tokens()).where(or_(AgentRun.case_id == case_id, AgentRun.dispute_id.in_(disputes)))
    return int(db.execute(q).scalar_one())


def global_tokens_today(db: Session, now: datetime | None = None) -> int:
    """全体の当日（UTC）の累計トークン数。"""
    day_start = datetime.combine((now or datetime.now(UTC)).date(), time.min, tzinfo=UTC)
    return int(db.execute(select(_tokens()).where(AgentRun.started_at >= day_start)).scalar_one())


def _warn_if_near(kind: str, scope: str, used: int, cap: int) -> None:
    if used >= cap * WARN_RATIO:
        log.warning("GRD-005: %s のトークン数が上限の %d%% に達しました（%s: %d / %d）",
                    kind, int(WARN_RATIO * 100), scope, used, cap)


def check_cost(db: Session, case_id: str | None, now: datetime | None = None) -> LimitHit | None:
    """GRD-005。全体を先に、次に案件を見る。案件に結び付かない実行は全体の上限にだけ従う。"""
    s = get_settings()
    used = global_tokens_today(db, now)
    if used >= s.agent_cost_tokens_per_day:
        return LimitHit("cost_global", used, s.agent_cost_tokens_per_day, "global")
    _warn_if_near("全体（1 日）", "global", used, s.agent_cost_tokens_per_day)
    if case_id:
        used = case_tokens(db, case_id)
        if used >= s.agent_cost_tokens_per_case:
            return LimitHit("cost_case", used, s.agent_cost_tokens_per_case, f"case:{case_id}")
        _warn_if_near("案件", f"case:{case_id}", used, s.agent_cost_tokens_per_case)
    return None


def _case_of_run(db: Session, run: AgentRun) -> str | None:
    """control.case_of_run と同じ規則（紛争の実行はその紛争の案件）。control は trace → llm を経由して
    このモジュールを import するため、循環を避けてここに置く。"""
    if run.case_id:
        return run.case_id
    if run.dispute_id:
        d = db.get(Dispute, run.dispute_id)
        return d.case_id if d else None
    return None


def check_before_llm(db: Session, run: AgentRun, now: datetime | None = None) -> LimitHit | None:
    """LLM を呼ぶ前の確認（反復・時間 → コスト）。llm.call_structured が呼ぶ。"""
    return check_run(run, now) or check_cost(db, _case_of_run(db, run), now)


# ---------------------------------------------------------------- GRD-003 / GRD-004: 件数


def check_task_count(case_id: str, count: int) -> LimitHit | None:
    """GRD-003: 1 案件あたりのタスク数。超過なら打ち切る（TOOL-004 / AG-002 の出力に対して呼ぶ）。"""
    cap = get_settings().agent_max_tasks_per_case
    return LimitHit("tasks", count, cap, f"case:{case_id}") if count > cap else None


def check_reconfirm(case_id: str, requested: int) -> LimitHit | None:
    """GRD-004: 1 案件あたりの再確認要求（TOOL-008）の回数。requested は要求済みの回数。上限に達していれば次を出さない。"""
    cap = get_settings().agent_max_reconfirms_per_case
    return LimitHit("reconfirms", requested, cap, f"case:{case_id}") if requested >= cap else None
