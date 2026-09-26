"""PM Agent の頭脳。Gemini でタスク分解・成果物生成・論点整理を行う。
GEMINI_API_KEY が無い場合は決定的なモック応答を返す（UI/フロー検証用）。
AI は提案・生成のみを行い、資金を動かす判断はしない。"""

import hashlib
import json
import logging
from typing import Literal

from pydantic import BaseModel, Field

from ..config import get_settings

log = logging.getLogger(__name__)

USDC = 1_000_000  # 6 decimals


class PlannedTask(BaseModel):
    title: str
    description: str
    type: Literal["ai", "human"]
    role: Literal["designer", "frontend", "backend", "qa", "field", "pm"]
    estimated_cost: int = Field(description="USDC 単位（整数）")


class TeamMember(BaseModel):
    name: str
    role: str
    kind: Literal["ai", "human"]


class Plan(BaseModel):
    summary: str
    tasks: list[PlannedTask]
    team: list[TeamMember]


class DisputeSummary(BaseModel):
    issues: list[str] = Field(description="争点")
    client_position: str
    agent_position: str
    facts_to_check: list[str]
    ai_note: str = Field(description="AI の参考所見。判断ではない")


class TaskCheck(BaseModel):
    meets_requirements: bool
    comment: str


def _client():
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


def _mock_plan(title: str, budget_usdc: int, fee_bps: int) -> Plan:
    usable = budget_usdc * (10_000 - fee_bps) // 10_000
    design = usable * 20 // 100
    front = usable * 30 // 100
    back = usable * 30 // 100
    field = usable * 10 // 100
    qa = usable - design - front - back - field
    return Plan(
        summary=f"「{title}」をデザイン→フロント→バックエンド→現地確認→QA の 5 タスクに分解しました。",
        tasks=[
            PlannedTask(title="画面デザイン", description="主要画面のワイヤーフレームとデザイン方針", type="ai", role="designer", estimated_cost=design),
            PlannedTask(title="フロントエンド実装", description="Next.js での画面実装方針とコンポーネント設計", type="ai", role="frontend", estimated_cost=front),
            PlannedTask(title="バックエンド実装", description="API 設計とデータモデル", type="ai", role="backend", estimated_cost=back),
            PlannedTask(title="現地の写真撮影", description="サービスで使う実店舗の外観写真を 3 枚撮影して URL を提出", type="human", role="field", estimated_cost=field),
            PlannedTask(title="受け入れテスト", description="完成条件に対するテスト観点と結果", type="ai", role="qa", estimated_cost=qa),
        ],
        team=[
            TeamMember(name="Designer Agent", role="designer", kind="ai"),
            TeamMember(name="Frontend Agent", role="frontend", kind="ai"),
            TeamMember(name="Backend Agent", role="backend", kind="ai"),
            TeamMember(name="Human Task Worker", role="field", kind="human"),
            TeamMember(name="QA Agent", role="qa", kind="ai"),
        ],
    )


def plan_case(*, agent_name: str, agent_rules: str, fee_bps: int, title: str, description: str, budget_usdc: int, deadline: str | None,
              subagent_rules: dict[str, str] | None = None) -> Plan:
    s = get_settings()
    if not s.gemini_enabled:
        return _mock_plan(title, budget_usdc, fee_bps)

    usable = budget_usdc * (10_000 - fee_bps) // 10_000
    system = (
        f"あなたは PM Agent「{agent_name}」です。以下は作成者が定めた進め方・ルールです。\n{agent_rules}\n\n"
        "あなたの役割は案件をタスクに分解し、AI 専門エージェントと人間のチームを編成することです。"
        "資金の支払い判断はしません。"
        + ("\n\nチームの専門エージェントごとの方針（所有者が設定。担当の割り当てと説明の参考にする）:\n"
           + "\n".join(f"- {r}: {t}" for r, t in subagent_rules.items()) if subagent_rules else "")
    )
    prompt = (
        f"案件: {title}\n説明: {description}\n納期: {deadline or '未指定'}\n"
        f"タスクに割り当てられる予算合計: {usable} USDC（あなたの手数料 {fee_bps / 100}% を除いた額）\n\n"
        "3〜6 個のタスクに分解してください。AI には向かない仕事（現地の写真撮影、実物確認、人間としての感想など）が"
        "1 つ以上あれば type=human にしてください。estimated_cost の合計は予算合計以下にしてください。"
        "日本語で書いてください。"
    )
    for attempt in range(3):
        plan = _generate(system, prompt, Plan)
        assert isinstance(plan, Plan)
        total = sum(t.estimated_cost for t in plan.tasks)
        if total <= usable and plan.tasks:
            return plan
        log.warning("plan over budget (%s > %s), retry %s", total, usable, attempt)
        prompt += f"\n\n前回は合計 {total} USDC で予算超過でした。合計を {usable} USDC 以下にしてください。"
    raise ValueError("予算内の計画を生成できませんでした")


# ---------------------------------------------------------------- execution


def execute_ai_task(*, agent_name: str, agent_rules: str, case_title: str, case_description: str, task_title: str, task_description: str, role: str,
                    role_rules: str = "") -> str:
    """AI 工程の成果物を生成する。role_rules は PM Agent の所有者が設定した、その専門エージェント（role）向けの追加プロンプト"""
    s = get_settings()
    if not s.gemini_enabled:
        h = hashlib.sha256(f"{case_title}:{task_title}".encode()).hexdigest()[:8]
        return (
            f"# {task_title}\n\n"
            f"担当: {role} Agent（{agent_name} チーム）\n\n"
            f"## 概要\n{task_description}\n\n"
            f"## 成果物\n- 案件「{case_title}」向けの {role} 成果物（モック）\n- 完成条件を満たすことを確認済み\n\n"
            f"## メモ\n生成 ID: {h}\n"
        )
    system = (
        f"あなたは PM Agent「{agent_name}」のチームに所属する {role} 専門の AI エージェントです。\n"
        f"PM の進め方・ルール:\n{agent_rules}\n"
        + (f"\n{role} 専門エージェントとしての方針（PM Agent の所有者が設定）:\n{role_rules}\n" if role_rules else "")
        + "成果物は Markdown で、具体的で発注者がそのまま検収できる粒度で書いてください。"
    )
    prompt = f"案件: {case_title}\n案件説明: {case_description}\n\n担当タスク: {task_title}\n{task_description}\n\n成果物を作成してください。日本語で。"
    return _generate_text(system, prompt)


def check_human_submission(*, task_title: str, task_description: str, submission: str) -> TaskCheck:
    s = get_settings()
    if not s.gemini_enabled:
        return TaskCheck(meets_requirements=True, comment="提出内容はタスクの完成条件を満たしています（モック確認）。")
    system = "あなたは PM Agent です。人間が提出した成果物がタスクの完成条件を満たすかを確認し、コメントします。"
    prompt = f"タスク: {task_title}\n完成条件/説明: {task_description}\n\n提出内容:\n{submission}"
    r = _generate(system, prompt, TaskCheck)
    assert isinstance(r, TaskCheck)
    return r


# ---------------------------------------------------------------- dispute


def summarize_dispute(*, case_title: str, case_description: str, plan_summary: str, deliverables: list[tuple[str, str]], reason: str) -> DisputeSummary:
    s = get_settings()
    if not s.gemini_enabled:
        return DisputeSummary(
            issues=["成果物が発注条件を満たしているか", "不足があるとすればどの範囲か"],
            client_position=reason,
            agent_position="計画に沿ってすべてのタスクの成果物を提出済み。",
            facts_to_check=["発注時の説明と成果物の対応関係", "不足箇所の具体的な指摘"],
            ai_note="AI は判断しません。支払い・返金は World で確認された Jury の多数決で決まります。",
        )
    system = "あなたは中立の仲介 AI です。発注者と PM Agent の主張を整理し、争点と確認すべき事実を提示します。支払いや返金の判断はしません。"
    body = "\n\n".join(f"### {t}\n{d[:3000]}" for t, d in deliverables)
    prompt = (
        f"案件: {case_title}\n説明: {case_description}\n計画: {plan_summary}\n\n"
        f"提出済み成果物:\n{body}\n\n発注者の差し戻し理由:\n{reason}\n\n日本語で論点を整理してください。"
    )
    r = _generate(system, prompt, DisputeSummary)
    assert isinstance(r, DisputeSummary)
    return r


# ---------------------------------------------------------------- human task assignment


class Assignment(BaseModel):
    ens_name: str = Field(description="選んだ人員の ENS 名。候補の中から選ぶ")
    reason: str = Field(description="選んだ理由（日本語・1〜2 文）")


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
        why = f"スキル「{best.get('skills')}」が{'タスク内容に合致し、' if hit else ''}拠点 {best.get('location') or '未設定'}・稼働可能のため（モック判定）"
        return Assignment(ens_name=best["ens_name"], reason=why)
    system = (
        f"あなたは PM Agent「{agent_name}」です。進め方・ルール:\n{agent_rules}\n"
        "人間にしかできないタスクを、ENS に登録された会社の人員の中から 1 名に指名します。"
        "スキル・拠点・役割・評価を根拠に選び、必ず候補の ENS 名をそのまま返してください。"
    )
    lines = "\n".join(f"- {c['ens_name']} | 会社: {c['company']} | 役割: {c['role']} | スキル: {c['skills']} | 拠点: {c['location']} | 評価: {c['rating']} ({c['completed']} 件)" for c in candidates)
    prompt = f"タスク: {task_title}\n{task_description}\n\n候補:\n{lines}\n\n1 名を指名し、理由を日本語で書いてください。"
    r = _generate(system, prompt, Assignment)
    assert isinstance(r, Assignment)
    if r.ens_name not in {c["ens_name"] for c in candidates}:
        r.ens_name = candidates[0]["ens_name"]
    return r
