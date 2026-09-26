"""AG-001 案件オーケストレータ: タスク分解とチーム編成の委譲とエスカレーション（WP-015 / agent-definitions AG-001・
agent-orchestration 5 章・12-3・13-1、HIL-005・GRD-004）。
DEC-007 (a): 次の操作は LLM（PMT-001・005・013）が選ぶ。ただし実行基盤が決定的なコードで縛る。
- 選べる操作は、その時点で 13-1 の順に許されるものだけ（ALLOWED）。それ以外は違反として再試行（PMT-013・CG-007）
- 操作と一緒に、委譲先から返った構造化データを返させる（PMT-005。2026-09-26 ユーザー回答）。データは手元の検証済みの出力と
  突き合わせ、違えば違反。**保存に使うのは手元の出力**で、モデルが返したデータは使わない
- ツールの引数（案件 ID・版番号・理由・違反項目）は実行基盤が埋める。金額と送金先をモデルに指定させない
- 委譲先には 5 章の表の項目だけを渡す（AG-002・AG-003 の関数が自分で読む）
- 各手順の前に停止（GRD-007）を確かめる。反復・時間・コストの上限は llm.call_structured が確かめる（GRD-005・11 章）
- 委譲先が失敗したら TOOL-008 で HIL-005（発注者へ再確認）へ差し戻す。AG-001 自身が上限に達したときや、受理できない指定が
  続いたときは、モデルに頼らず実行基盤が TOOL-008 を呼ぶ
既存の tasks にはまだ書かない（切り替えは WP-018）。既存の /cases の流れは変えない。
紛争モード（WP-016 / 13-3）: AG-004 → TOOL-007。AG-004 が失敗しても例外にせず「論点なし」で返し、裁定（HIL-004）は止めない。"""

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from ..models import AgentRun, Case, Dispute
from . import ag002_decompose, ag003_team, ag004_dispute, context, control, llm, tools, trace
from . import tool_dispute, tool_plan, tool_progress, tool_reconfirm, tool_team  # noqa: F401  TOOL-004〜008 を登録する
from .ag002_decompose import DecomposeResult
from .ag003_team import TeamResult
from .ag004_dispute import DisputeResult
from .guards import neutralize, normalize
from .limits import LimitHit
from .tool_dispute import DisputeSummary
from .tool_plan import TaskPlan
from .tool_team import TeamProposal
from .trace import redact

log = logging.getLogger(__name__)

Action = Literal["delegate_decompose", "save_task_plan", "delegate_form_team", "save_team_proposal", "request_reconfirmation",
                 "delegate_analyze_dispute", "save_dispute_summary", "finish"]
Phase = Literal["start", "decomposed", "decompose_failed", "plan_saved", "team_formed", "team_failed", "team_saved",
                "dispute_start", "analyzed", "no_issues", "summary_saved"]

# 13-1 の順。失敗したら HIL-005 だけ（委譲先は自分で最大 3 回試している）
ALLOWED: dict[str, tuple[str, ...]] = {
    "start": ("delegate_decompose",),
    "decomposed": ("save_task_plan",),
    "decompose_failed": ("request_reconfirmation",),
    "plan_saved": ("delegate_form_team",),
    "team_formed": ("save_team_proposal",),
    "team_failed": ("request_reconfirmation",),
    "team_saved": ("finish",),
    # 13-3 紛争: 論点なしでも HIL-004（裁定）へ進むので、差し戻しは無い
    "dispute_start": ("delegate_analyze_dispute",),
    "analyzed": ("save_dispute_summary",),
    "no_issues": ("finish",),
    "summary_saved": ("finish",),
}
MAX_INVALID = 3  # 受理できない指定が続いたら、実行基盤が HIL-005 へ差し戻す（PMT-013 の再試行の上限）


class Ag001Step(BaseModel):
    """AG-001 の出力: 次の操作と、委譲先から返った構造化データ（そのまま）。PMT-001・005"""
    model_config = ConfigDict(extra="forbid")
    action: Action
    task_plan: TaskPlan | None = None
    team_proposal: TeamProposal | None = None
    dispute_summary: DisputeSummary | None = None


@dataclass
class PlanningResult:
    ok: bool
    run_id: str
    plan_revision: int | None = None
    team_revision: int | None = None
    escalated: bool = False  # HIL-005 へ差し戻した
    case_stopped: bool = False  # GRD-004 で案件を止めた
    reason: str | None = None
    violations: list[str] = field(default_factory=list)
    limit_hit: LimitHit | None = None


@dataclass
class _State:
    phase: Phase = "start"
    decompose: DecomposeResult | None = None
    team: TeamResult | None = None
    plan_revision: int | None = None
    team_revision: int | None = None
    fail_reason: str | None = None
    fail_violations: list[str] = field(default_factory=list)
    limit_hit: LimitHit | None = None
    dispute: DisputeResult | None = None
    dispute_revision: int | None = None


@dataclass
class DisputeRunResult:
    """紛争モードの結果。no_issues が真でも裁定（HIL-004）は進める"""
    ok: bool
    run_id: str
    summary_revision: int | None = None
    no_issues: bool = False
    reason: str | None = None
    violations: list[str] = field(default_factory=list)


def _canon(value: object) -> object:
    """コンテキストに入れるときと同じ正規化（CG-003・CG-001）をした値。突き合わせに使う。"""
    if isinstance(value, str):
        return neutralize(normalize(value))
    if isinstance(value, list):
        return [_canon(v) for v in value]
    if isinstance(value, dict):
        return {k: _canon(v) for k, v in value.items()}
    return value


def _payload(st: _State) -> tuple[str, dict] | None:
    """いま AG-001 に見せる委譲先の構造化データ（CTX-006。依頼文由来の自由文を含むので信頼できない入力として区切る）。"""
    if st.phase == "decomposed":
        return "task_plan", st.decompose.plan.model_dump()
    if st.phase == "team_formed":
        return "team_proposal", st.team.proposal.model_dump()
    if st.phase == "analyzed":
        return "dispute_summary", st.dispute.summary.model_dump()
    return None


def _state_view(st: _State) -> dict:
    """CTX-005: 現在の手順と案件の状態（決定的に作る。金額・送金先・policy・候補は入れない）。"""
    view = {"phase": st.phase, "allowed_actions": list(ALLOWED[st.phase]), "plan_revision": st.plan_revision,
            "team_revision": st.team_revision, "dispute_revision": st.dispute_revision}
    if st.decompose is not None and st.decompose.ok:
        view["task_count"] = len(st.decompose.plan.tasks)
    if st.fail_reason:
        view["failure"] = {"reason": st.fail_reason, "violations": st.fail_violations}
    return view


def expected_step(st: _State) -> dict:
    """GEMINI_API_KEY が無いときの決定的な応答: 許される操作と、見せたデータをそのまま返す。"""
    step: dict = {"action": ALLOWED[st.phase][0]}
    p = _payload(st)
    if p is not None:
        step[p[0]] = p[1]
    return step


def validate_step(step: Ag001Step, st: _State) -> list[str]:
    """実行基盤の検証。違反項目にモデルの出力値を入れない（CG-007）。"""
    out: list[str] = []
    if step.action not in ALLOWED[st.phase]:
        out.append(f"This action is not allowed at this point (allowed actions: {', '.join(ALLOWED[st.phase])})")
    p = _payload(st)
    given = {"task_plan": step.task_plan, "team_proposal": step.team_proposal, "dispute_summary": step.dispute_summary}
    for key, value in given.items():
        if p is not None and key == p[0]:
            if value is None:
                out.append(f"{key} is missing (include the data returned by the delegate as is)")
            elif _canon(value.model_dump()) != _canon(p[1]):
                out.append(f"{key} does not match the data returned by the delegate (include it without changes)")
        elif value is not None:
            out.append(f"{key} must not be included at this point")
    return out


@dataclass
class _Ask:
    """AG-001 に 1 回問い合わせた結果"""
    kind: Literal["stopped", "limit", "llm_error", "invalid", "ok"]
    step: Ag001Step | None = None
    violations: list[str] = field(default_factory=list)
    limit_hit: LimitHit | None = None
    reason: str | None = None


def _ask(db: Session, run, st: _State, violations: list[str], mock: Callable[[], str | dict] | None) -> _Ask:
    """停止の確認（GRD-007）→ コンテキスト（CTX-005・006・008）→ モデル → 記録 → 形と実行基盤の検証。"""
    if control.state_for_run(db, run).stopped:
        return _Ask("stopped")
    payload = _payload(st)
    texts = [json.dumps({payload[0]: payload[1]}, ensure_ascii=False, sort_keys=True)] if payload else []
    ctx = context.build_ag001(state=_state_view(st), texts=texts, schema=Ag001Step, violations=violations)
    r = llm.call_structured(db=db, run=run, agent_id="AG-001", system=ctx.system, contents=ctx.contents, schema=Ag001Step,
                            mock=mock or (lambda: expected_step(st)))
    if r.failure == "limit":
        return _Ask("limit", limit_hit=r.limit_hit)
    trace.record_llm(db, run, r, ctx.truncations)
    if r.failure in ("timeout", "error", "unavailable"):
        return _Ask("llm_error", violations=[f"{r.failure}: {r.detail}"], reason="unavailable" if r.failure == "unavailable" else "llm_error")
    if r.failure in ("parse", "schema"):
        return _Ask("invalid", violations=[f"Output does not match the expected format ({r.failure}): {r.detail}"])
    found = validate_step(r.output, st)
    if found:  # 12-1: 実行基盤の検証で違反した項目も実行の記録に残す（record_llm は形の違反だけを積む）
        run.validation_failures = [*(run.validation_failures or []), *(redact(v)[:1000] for v in found)]
        db.commit()
        return _Ask("invalid", violations=found)
    return _Ask("ok", step=r.output)


def run_planning(db: Session, *, case_id: str, run: AgentRun | None = None, mock: Callable[[], str | dict] | None = None,
                 mock_ag002: Callable[[], str | dict] | None = None, mock_ag003: Callable[[], str | dict] | None = None) -> PlanningResult:
    """1 つの案件について、AG-002 → TOOL-004 → AG-003 → TOOL-005 を進める。失敗は TOOL-008（HIL-005）へ。
    run はランナーが取り出したジョブ行（WP-017）。無ければここで実行を始める。"""
    case = db.get(Case, case_id)
    if case is None:
        raise ValueError(f"Case not found: {case_id}")
    run = run or trace.start_run(db, "AG-001", mode="plan", case_id=case_id, input_text=case.title)
    st = _State()
    violations: list[str] = []
    invalid = 0

    def finish(status: str, **kw) -> PlanningResult:
        r = PlanningResult(ok=kw.pop("ok", False), run_id=run.id, plan_revision=st.plan_revision, team_revision=st.team_revision, **kw)
        trace.finish_run(db, run, status, error=None if r.ok else f"{r.reason}: " + " / ".join(r.violations))
        return r

    def escalate(reason: str, items: list[str], hit: LimitHit | None = None) -> PlanningResult:
        """HIL-005: TOOL-008 を呼ぶ（引数は手元の値から）。GRD-005 なら運用者にも知らせる（ログ。12-3）。"""
        if hit is not None and hit.kind.startswith("cost"):
            log.warning("GRD-005: コストの上限に達したため HIL-005 へ差し戻します（case:%s、%s）", case_id, hit.detail)
        res = tools.call_tool(db, run, "TOOL-008", case_id=case_id, reason=reason, violations=items)
        if res.stopped:
            return finish("stopped", reason="stopped", violations=items)
        stopped_case = bool(res.ok and res.value.get("case_stopped"))
        status = "stopped" if stopped_case or (hit is not None and hit.kind.startswith("cost")) else "failed"
        return finish(status, escalated=res.ok, case_stopped=stopped_case, reason=reason,
                      violations=items if res.ok else [*items, res.error or ""], limit_hit=hit)

    while True:
        a = _ask(db, run, st, violations, mock)  # GRD-007: 各手順の前に停止を確かめる
        if a.kind == "stopped":
            return finish("stopped", reason="stopped", violations=violations)
        if a.kind == "limit":  # AG-001 自身の上限（11 章: 案件を止めて HIL-005）
            if st.phase == "team_saved":  # 保存は済んでいる。終える指定だけが出せなかった
                return finish("done", ok=True)
            return escalate("limit", [a.limit_hit.detail], a.limit_hit)
        if a.kind == "llm_error":
            return escalate(a.reason, a.violations)
        violations = a.violations
        if a.kind == "invalid":
            invalid += 1
            if invalid >= MAX_INVALID:
                return escalate("orchestrator", violations)
            continue
        invalid = 0
        action = a.step.action

        if action == "delegate_decompose":  # 5 章: 依頼文と phases だけ（decompose が自分で読む）
            st.decompose = ag002_decompose.decompose(db, case_id=case_id, parent_run_id=run.id, mock=mock_ag002)
            if st.decompose.reason == "stopped":
                return finish("stopped", reason="stopped")
            st.phase = "decomposed" if st.decompose.ok else "decompose_failed"
            if not st.decompose.ok:
                st.fail_reason, st.fail_violations, st.limit_hit = st.decompose.reason, st.decompose.violations, st.decompose.limit_hit
        elif action == "save_task_plan":  # TOOL-004（手元の検証済みの出力を渡す）
            rev = trace.revision_for_run(db, "task_plan", case_id, run)  # 再開しても同じ版（10 章）
            res = tools.call_tool(db, run, "TOOL-004", case_id=case_id, revision=rev, tasks=st.decompose.plan.model_dump()["tasks"])
            if res.stopped:
                return finish("stopped", reason="stopped")
            if res.ok:
                st.phase, st.plan_revision = "plan_saved", rev
            else:
                st.phase, st.fail_reason, st.fail_violations = "decompose_failed", "tool_error", [res.error or ""]
        elif action == "delegate_form_team":  # 5 章: タスク一覧・予算・human_roles（form_team が保存済みの計画から読む）
            st.team = ag003_team.form_team(db, case_id=case_id, parent_run_id=run.id, mock=mock_ag003)
            if st.team.reason == "stopped":
                return finish("stopped", reason="stopped")
            st.phase = "team_formed" if st.team.ok else "team_failed"
            if not st.team.ok:
                st.fail_reason, st.fail_violations, st.limit_hit = st.team.reason, st.team.violations, st.team.limit_hit
        elif action == "save_team_proposal":  # TOOL-005（GRD-002 はツールの中でもう一度）
            rev = trace.revision_for_run(db, "team_proposal", case_id, run)
            res = tools.call_tool(db, run, "TOOL-005", case_id=case_id, revision=rev, items=st.team.proposal.model_dump()["items"])
            if res.stopped:
                return finish("stopped", reason="stopped")
            if res.ok:
                st.phase, st.team_revision = "team_saved", rev
            else:
                st.phase, st.fail_reason, st.fail_violations = "team_failed", "tool_error", [res.error or ""]
        elif action == "request_reconfirmation":  # HIL-005（理由と違反項目は手元の値）
            return escalate(st.fail_reason or "violations", st.fail_violations, st.limit_hit)
        elif action == "finish":
            return finish("done", ok=True)
        else:  # 紛争の操作は ALLOWED で弾かれるので、ここには来ない
            raise AssertionError(f"Action not handled in plan mode: {action}")


def run_dispute(db: Session, *, dispute_id: str, run: AgentRun | None = None, mock: Callable[[], str | dict] | None = None,
                mock_ag004: Callable[[], str | dict] | None = None) -> DisputeRunResult:
    """13-3: AG-004 に論点整理を委譲し、合格した論点を TOOL-007 で保存する。
    どこで失敗しても例外にせず「論点なし」で返す（裁定は人間が行えるため、HIL-004 を止めない）。"""
    d = db.get(Dispute, dispute_id)
    if d is None:
        raise ValueError(f"Dispute not found: {dispute_id}")
    run = run or trace.start_run(db, "AG-001", mode="analyze_dispute", dispute_id=dispute_id, input_text=d.reason or "")
    st = _State(phase="dispute_start")
    violations: list[str] = []
    invalid = 0

    def finish(status: str, **kw) -> DisputeRunResult:
        r = DisputeRunResult(ok=kw.pop("ok", False), run_id=run.id, summary_revision=st.dispute_revision, **kw)
        trace.finish_run(db, run, status, error=None if r.ok else f"{r.reason}: " + " / ".join(r.violations))
        return r

    def no_issues(reason: str, items: list[str], status: str = "done") -> DisputeRunResult:
        return finish(status, no_issues=True, reason=reason, violations=items)

    while True:
        a = _ask(db, run, st, violations, mock)
        if a.kind == "stopped":
            return no_issues("stopped", violations, "stopped")
        if a.kind == "limit":
            if st.phase == "summary_saved":
                return finish("done", ok=True)
            return no_issues("limit", [a.limit_hit.detail], "stopped" if a.limit_hit.kind.startswith("cost") else "failed")
        if a.kind == "llm_error":
            return no_issues(a.reason, a.violations, "failed")
        violations = a.violations
        if a.kind == "invalid":
            invalid += 1
            if invalid >= MAX_INVALID:
                return no_issues("orchestrator", violations, "failed")
            continue
        invalid = 0
        action = a.step.action

        if action == "delegate_analyze_dispute":  # 5 章: 紛争 ID・主張の要約・記録（analyze が自分で読む）
            st.dispute = ag004_dispute.analyze(db, dispute_id=dispute_id, parent_run_id=run.id, mock=mock_ag004)
            if st.dispute.reason == "stopped":
                return no_issues("stopped", [], "stopped")
            st.phase = "analyzed" if st.dispute.ok else "no_issues"
            if not st.dispute.ok:
                st.fail_reason, st.fail_violations = st.dispute.reason, st.dispute.violations
        elif action == "save_dispute_summary":  # TOOL-007（手元の検証済みの出力を渡す）
            rev = trace.revision_for_run(db, "dispute_summary", dispute_id, run)
            res = tools.call_tool(db, run, "TOOL-007", dispute_id=dispute_id, revision=rev, issues=st.dispute.summary.model_dump()["issues"])
            if res.stopped:
                return no_issues("stopped", [], "stopped")
            if res.ok:
                st.phase, st.dispute_revision = "summary_saved", rev
            else:
                st.phase, st.fail_reason, st.fail_violations = "no_issues", "tool_error", [res.error or ""]
        elif action == "finish":
            if st.phase == "summary_saved":
                return finish("done", ok=True)
            return no_issues(st.fail_reason or "violations", st.fail_violations)  # 論点なしのまま HIL-004 へ
        else:  # 計画の操作は ALLOWED で弾かれるので、ここには来ない
            raise AssertionError(f"Action not handled in dispute mode: {action}")
