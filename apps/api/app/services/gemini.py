"""PM Agent の頭脳。Gemini でタスク分解・成果物生成・論点整理を行う。
GEMINI_API_KEY が無い場合は決定的なモック応答を返す（UI/フロー検証用）。
AI は提案・生成のみを行い、資金を動かす判断はしない。"""

import hashlib
import json
import logging
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field

from ..config import get_settings

log = logging.getLogger(__name__)

USDC = 1_000_000  # 6 decimals


class PlannedTask(BaseModel):
    title: str
    description: str
    type: Literal["ai", "human"]
    role: str = Field(description="If type=ai, one of the specialist agent roles; if type=human, field")
    estimated_cost: int = Field(description="In USDC (integer)")


class TeamMember(BaseModel):
    name: str
    role: str
    kind: Literal["ai", "human"]


class Plan(BaseModel):
    summary: str
    tasks: list[PlannedTask]
    team: list[TeamMember]


class DisputeSummary(BaseModel):
    issues: list[str] = Field(description="Points of dispute")
    client_position: str
    agent_position: str
    facts_to_check: list[str]
    ai_note: str = Field(description="AI's reference notes. Not a ruling")


class TaskCheck(BaseModel):
    meets_requirements: bool
    comment: str


@lru_cache(maxsize=1)
def _client():
    """Client は保持しておく。使い捨てにすると回収時に接続が閉じられ、送信前に RuntimeError になる。"""
    from google import genai

    return genai.Client(api_key=get_settings().gemini_api_key)


def _generate(system: str, prompt: str, schema: type[BaseModel]) -> BaseModel:
    from google.genai import types

    s = get_settings()
    resp = _client().models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=system,
            response_mime_type="application/json",
            response_schema=schema,
            temperature=0.4,
        ),
    )
    if resp.parsed is not None:
        return resp.parsed  # type: ignore[return-value]
    return schema.model_validate(json.loads(resp.text or "{}"))


def _generate_text(system: str, prompt: str) -> str:
    from google.genai import types

    s = get_settings()
    resp = _client().models.generate_content(
        model=s.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=system, temperature=0.6),
    )
    return resp.text or ""


# ---------------------------------------------------------------- planning


_MOCK_TASK_TEXT = {
    "designer": ("Screen design", "Wireframes and design direction for the main screens"),
    "frontend": ("Frontend implementation", "Screen implementation approach in Next.js and component design"),
    "backend": ("Backend implementation", "API design and data model"),
    "qa": ("Acceptance testing", "Test criteria and results against the completion criteria"),
}


def _mock_plan(title: str, budget_usdc: int, fee_bps: int, subagents: list[dict] | None = None) -> Plan:
    """決定的なモック計画。所有者が定義した専門エージェント（最大 4 件）に AI タスクを 1 つずつ割り当て、Human Task を 1 つ入れる"""
    from .ens import DEFAULT_SUBAGENTS

    subs = (subagents if subagents else DEFAULT_SUBAGENTS)[:4]
    usable = budget_usdc * (10_000 - fee_bps) // 10_000
    field = usable * 10 // 100
    rest = usable - field
    n = len(subs)
    tasks, team = [], []
    for i, sub in enumerate(subs):
        cost = rest // n if i < n - 1 else rest - (rest // n) * (n - 1)
        t_title, t_desc = _MOCK_TASK_TEXT.get(sub["role"], (f"{sub.get('name') or sub['role']} work", sub.get("description") or f"Deliverable as {sub['role']}"))
        tasks.append(PlannedTask(title=t_title, description=t_desc, type="ai", role=sub["role"], estimated_cost=cost))
        team.append(TeamMember(name=sub.get("name") or f"{sub['role']} Agent", role=sub["role"], kind="ai"))
    # Human Task は QA の前（既定の並び）に入れる
    pos = max(len(tasks) - 1, 0)
    tasks.insert(pos, PlannedTask(title="On-site photography", description="Take 3 exterior photos of the physical store used by the service and submit the URLs", type="human", role="field", estimated_cost=field))
    team.insert(pos, TeamMember(name="Human Task Worker", role="field", kind="human"))
    return Plan(summary=f"Broke down \"{title}\" into {len(tasks)} Tasks: {' → '.join(t.title for t in tasks)}.", tasks=tasks, team=team)


def plan_case(*, agent_name: str, agent_rules: str, fee_bps: int, title: str, description: str, budget_usdc: int, deadline: str | None,
              subagents: list[dict] | None = None) -> Plan:
    """案件をタスクに分解する。type=ai のタスクの role は、所有者が定義した専門エージェント（subagents）の role に限る"""
    s = get_settings()
    if not s.gemini_enabled:
        return _mock_plan(title, budget_usdc, fee_bps, subagents)
    subs = subagents or []
    roles = [x["role"] for x in subs]

    usable = budget_usdc * (10_000 - fee_bps) // 10_000
    system = (
        f"You are the PM Agent \"{agent_name}\". Below are the working methods and rules set by the creator.\n{agent_rules}\n\n"
        "Your role is to break the Case down into Tasks and build a team of specialist AI agents and humans. "
        "You do not make any decisions about paying out funds."
        + ("\n\nSpecialist AI agents available to the team (choose the role of type=ai Tasks from these; use these names for team[].name):\n"
           + "\n".join(f"- role={x['role']}: {x.get('name') or x['role']}" + (f" — {x['description']}" if x.get("description") else "") + (f" (policy: {x['rules'][:200]})" if x.get("rules") else "") for x in subs)
           if subs else "\n\n(No specialist AI agents are defined. Use role=general for type=ai Tasks.)")
        + "\nTasks for humans use type=human, role=field."
    )
    prompt = (
        f"Case: {title}\nDescription: {description}\nDeadline: {deadline or 'Not specified'}\n"
        f"Total budget available for Tasks: {usable} USDC (excluding your fee of {fee_bps / 100}%)\n\n"
        "Break it down into 3-6 Tasks. If there is at least one job unsuited to AI (on-site photography, checking physical items, human impressions, etc.), "
        "make it type=human. The sum of estimated_cost must not exceed the total budget. "
        "Write in English."
    )
    for attempt in range(3):
        plan = _generate(system, prompt, Plan)
        assert isinstance(plan, Plan)
        # role の正規化: ai は定義済みの role だけ、human は field
        for t in plan.tasks:
            if t.type == "human":
                t.role = "field"
            elif roles and t.role not in roles:
                log.warning("plan: unknown ai role %r → %r", t.role, roles[0])
                t.role = roles[0]
        total = sum(t.estimated_cost for t in plan.tasks)
        if total <= usable and plan.tasks:
            return plan
        log.warning("plan over budget (%s > %s), retry %s", total, usable, attempt)
        prompt += f"\n\nLast time the total was {total} USDC, which exceeded the budget. Keep the total at or below {usable} USDC."
    raise ValueError("Could not generate a plan within the budget")


# ---------------------------------------------------------------- execution


def execute_ai_task(*, agent_name: str, agent_rules: str, case_title: str, case_description: str, task_title: str, task_description: str, role: str,
                    role_rules: str = "", role_name: str = "") -> str:
    """AI 工程の成果物を生成する。role_rules / role_name は PM Agent の所有者が定義した、その専門エージェント（role）のプロンプトと名前"""
    s = get_settings()
    if not s.gemini_enabled:
        h = hashlib.sha256(f"{case_title}:{task_title}".encode()).hexdigest()[:8]
        return (
            f"# {task_title}\n\n"
            f"Assignee: {role} Agent ({agent_name} team)\n\n"
            f"## Overview\n{task_description}\n\n"
            f"## Deliverable\n- {role} Deliverable for the Case \"{case_title}\" (mock)\n- Verified to meet the completion criteria\n\n"
            f"## Notes\nGeneration ID: {h}\n"
        )
    system = (
        f"You are \"{role_name or role}\", a specialist AI agent for {role} on the team of the PM Agent \"{agent_name}\".\n"
        f"PM working methods and rules:\n{agent_rules}\n"
        + (f"\nPolicy as the {role} specialist agent (set by the PM Agent owner):\n{role_rules}\n" if role_rules else "")
        + "Write the Deliverable in Markdown, concretely and in enough detail for the Client to review and accept it as-is. Write in English."
    )
    prompt = f"Case: {case_title}\nCase description: {case_description}\n\nAssigned Task: {task_title}\n{task_description}\n\nCreate the Deliverable. Write in English."
    return _generate_text(system, prompt)


def check_human_submission(*, task_title: str, task_description: str, submission: str) -> TaskCheck:
    s = get_settings()
    if not s.gemini_enabled:
        return TaskCheck(meets_requirements=True, comment="The submission meets the Task's completion criteria (mock check).")
    system = "You are a PM Agent. Check whether the Deliverable submitted by a human meets the Task's completion criteria, and comment on it. Write in English."
    prompt = f"Task: {task_title}\nCompletion criteria / description: {task_description}\n\nSubmission:\n{submission}"
    r = _generate(system, prompt, TaskCheck)
    assert isinstance(r, TaskCheck)
    return r


# ---------------------------------------------------------------- dispute


def summarize_dispute(*, case_title: str, case_description: str, plan_summary: str, deliverables: list[tuple[str, str]], reason: str) -> DisputeSummary:
    s = get_settings()
    if not s.gemini_enabled:
        return DisputeSummary(
            issues=["Whether the Deliverables meet the order requirements", "If anything is missing, what scope it covers"],
            client_position=reason,
            agent_position="Deliverables for all Tasks have been submitted according to the plan.",
            facts_to_check=["How the Deliverables correspond to the original request description", "Specific points on what is missing"],
            ai_note="AI does not make the decision. Payment or refund is decided by a majority vote of the World-verified Jury.",
        )
    system = "You are a neutral mediator AI. Organize the positions of the Client and the PM Agent, and present the points of dispute and the facts to verify. You do not decide on payment or refund. Write in English."
    body = "\n\n".join(f"### {t}\n{d[:3000]}" for t, d in deliverables)
    prompt = (
        f"Case: {case_title}\nDescription: {case_description}\nPlan: {plan_summary}\n\n"
        f"Submitted Deliverables:\n{body}\n\nClient's reason for sending back:\n{reason}\n\nOrganize the points of dispute in English."
    )
    r = _generate(system, prompt, DisputeSummary)
    assert isinstance(r, DisputeSummary)
    return r


# ---------------------------------------------------------------- human task assignment


class Assignment(BaseModel):
    ens_name: str = Field(description="ENS name of the chosen Member. Choose from the candidates")
    reason: str = Field(description="Reason for the choice (in English, 1-2 sentences)")


def assign_human_task(*, agent_name: str, agent_rules: str, task_title: str, task_description: str, candidates: list[dict]) -> Assignment | None:
    """候補（ENS レコード）から 1 名を指名する。候補が無ければ None。"""
    if not candidates:
        return None
    s = get_settings()
    if not s.gemini_enabled:
        words = {w for w in (task_title + " " + task_description).lower().replace("、", " ").split() if len(w) > 1}
        def score(c: dict) -> tuple[int, float]:
            skills = [x.strip().lower() for x in c.get("skills", "").split(",") if x.strip()]
            hit = sum(1 for sk in skills if any(sk in w or w in sk for w in words))
            return (hit, float(c.get("rating", 0)))
        best = max(candidates, key=score)
        hit, _ = score(best)
        why = f"Chosen for skills \"{best.get('skills')}\"{' (match the Task)' if hit else ''}, location {best.get('location') or 'Not configured'}, and availability (mock decision)"
        return Assignment(ens_name=best["ens_name"], reason=why)
    system = (
        f"You are the PM Agent \"{agent_name}\". Working methods and rules:\n{agent_rules}\n"
        "Assign a Task that only a human can do to one Member of a Company registered on ENS. "
        "Choose based on skills, location, role, and rating, and always return the candidate's ENS name exactly as given."
    )
    lines = "\n".join(f"- {c['ens_name']} | Company: {c['company']} | Role: {c['role']} | Skills: {c['skills']} | Location: {c['location']} | Rating: {c['rating']} ({c['completed']} completed)" for c in candidates)
    prompt = f"Task: {task_title}\n{task_description}\n\nCandidates:\n{lines}\n\nAssign one person and write the reason in English."
    r = _generate(system, prompt, Assignment)
    assert isinstance(r, Assignment)
    if r.ens_name not in {c["ens_name"] for c in candidates}:
        r.ens_name = candidates[0]["ens_name"]
    return r
