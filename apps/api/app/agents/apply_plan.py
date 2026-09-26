"""計画の結果を tasks に写し、HIL-002（発注者の承諾）へつなぐ（WP-018 / agent-orchestration 7 章 HIL-002・13-1）。
AG-001 の実行（計画）が正常に終わったあと、ランナーが呼ぶ。エージェントではなく決定的なコードで、LLM は呼ばない。
- 写すのは、同じ AG-001 の実行が保存したタスク計画（TOOL-004）とチーム案（TOOL-005）
- tasks の列: order_no = seq - 1、title、type（human / ai_agent → human / ai）、role = phase、estimated_cost = amount、
  assignee_name = 担当の名前（ENS 名から DB の索引で引く）
- PM 管理費のタスク（CON-006）は既存の _plan_job と同じく、予算の残額で作る
- 書き込みの前に、対応（全タスクに担当が 1 つ）と GRD-002（合計 <= 手数料を除いた予算）を決定的なコードでもう一度確かめる
- plan_json には要約とチームを入れ、画面の表示（要約・チームの一覧）を保つ。要約はコードが作る（LLM を呼ばない）
- 案件の状態は awaiting_approval（HIL-002 の待機）にする。金額と送金先を決めるのは発注者の承諾（AQ-010）
写せないときは planning_failed にして理由を残す（WP-015 の差し戻しと同じ状態。/replan でやり直せる）。"""

import logging

from sqlalchemy.orm import Session

from ..models import Agent, AgentOutput, AgentRun, Case, Member, Task
from ..services import chain
from ..services.gemini import USDC
from .tool_team import usable_budget

log = logging.getLogger(__name__)

KIND_TO_TYPE = {"ai_agent": "ai", "human": "human"}
FEE_TASK_TITLE = "PM management (task breakdown, team building, progress tracking)"


class PlanNotApplicable(Exception):
    """保存された計画を tasks に写せない（理由はメッセージ）"""


def _outputs_of_run(db: Session, run: AgentRun) -> tuple[AgentOutput, AgentOutput]:
    """この実行が保存したタスク計画とチーム案（それぞれ最新の版）"""
    def one(kind: str) -> AgentOutput | None:
        return (db.query(AgentOutput).filter_by(kind=kind, target_id=run.case_id, run_id=run.id)
                .order_by(AgentOutput.revision.desc()).first())

    plan, team = one("task_plan"), one("team_proposal")
    if plan is None or team is None:
        raise PlanNotApplicable("The task plan or team proposal for this run has not been saved")
    return plan, team


def _assignee_name(db: Session, kind: str, ens_name: str) -> str:
    if kind == "ai_agent":
        name = db.query(Agent.name).filter(Agent.ens_name == ens_name).scalar()
    else:
        name = db.query(Member.name).filter(Member.ens_name == ens_name).scalar()
    return name or ens_name


def summarize(tasks: list[dict], team: list[dict], fee: int) -> str:
    """plan_json.summary。件数・工程キー・チームの人数・PM 管理費だけで作る（モデルの自由文を入れない）"""
    phases = list(dict.fromkeys(t["phase"] for t in tasks))
    return (f"Splits {len(tasks)} tasks into {len(phases)} steps ({', '.join(phases)}) handled by a team of {len(team)}. "
            f"Includes a PM fee of {fee / USDC:g} USDC.")


def build_tasks(db: Session, case: Case, agent: Agent, plan: dict, team: dict) -> tuple[list[Task], dict]:
    """(tasks の行, plan_json) を作る。検証に通らなければ PlanNotApplicable。"""
    tasks, items = plan["tasks"], team["items"]
    by_seq = {i["task_seq"]: i for i in items}
    if sorted(by_seq) != sorted(t["seq"] for t in tasks) or len(by_seq) != len(items):
        raise PlanNotApplicable("The sequence numbers of the task plan and team proposal do not match")
    kinds = {i["assignee_kind"] for i in items}
    if not kinds <= set(KIND_TO_TYPE):
        raise PlanNotApplicable("Unknown assignee type")
    total = sum(int(i["amount"]) for i in items)
    if total > usable_budget(case, agent):  # GRD-002（保存時と同じ判定を、書き込みの前にもう一度）
        raise PlanNotApplicable(f"The total amount exceeds the budget (excess: {total - usable_budget(case, agent)})")
    fee = int(case.budget) - total

    rows: list[Task] = []
    team_json: list[dict] = []
    for t in sorted(tasks, key=lambda x: x["seq"]):
        item = by_seq[t["seq"]]
        name = _assignee_name(db, item["assignee_kind"], item["assignee_ens_name"])
        rows.append(Task(case_id=case.id, order_no=t["seq"] - 1, title=t["title"][:200], description="",
                         type=KIND_TO_TYPE[item["assignee_kind"]], role=t["phase"], estimated_cost=int(item["amount"]),
                         assignee_name=name[:120]))
        member = {"name": name, "role": t["phase"], "kind": KIND_TO_TYPE[item["assignee_kind"]]}
        if member not in team_json:
            team_json.append(member)
    summary = summarize(tasks, team_json, fee)
    # PM 管理費もタスク（工程）として契約する（CON-006、Creator の収益）
    rows.append(Task(case_id=case.id, order_no=len(tasks), title=FEE_TASK_TITLE, description=summary,
                     type="ai", role="pm", estimated_cost=fee, assignee_name=agent.name))
    return rows, {"summary": summary, "team": team_json, "source": "agents"}


def apply(db: Session, run: AgentRun) -> bool:
    """正常に終わった計画の実行（run）の結果を tasks に写し、awaiting_approval にする。写したら True。
    案件が planning でない・すでに tasks がある場合は何もしない（冪等）。写せなければ planning_failed。"""
    # 状態は DB から読み直す（expire_on_commit=False のため、ランナーのセッションは /replan など別のセッションの変更を見ていない）
    case = db.get(Case, run.case_id, populate_existing=True)
    if case is None or case.status != "planning":
        return False
    if db.query(Task.id).filter(Task.case_id == case.id).first():
        return False
    try:
        plan, team = _outputs_of_run(db, run)
        rows, plan_json = build_tasks(db, case, db.get(Agent, case.agent_id), plan.payload, team.payload)
    except PlanNotApplicable as e:
        log.warning("計画を tasks に写せません（case:%s）: %s", case.id, e)
        case.status, case.error = "planning_failed", f"Could not apply the plan: {e}"
        db.commit()
        return False
    plan_json.update({"task_plan_revision": plan.revision, "team_proposal_revision": team.revision})
    db.add_all(rows)
    db.flush()
    for t in rows:
        t.escrow_task_id = chain.escrow_task_id(t.id)
    case.plan_json = plan_json
    case.status, case.error = "awaiting_approval", None  # HIL-002
    db.commit()
    return True
