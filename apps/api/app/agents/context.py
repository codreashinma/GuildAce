"""エージェントに渡すコンテキストの組み立て（WP-004 / agent-context 4〜8 章・context-templates）。
- system: CTX-001（役割 PMT-001〜004）→ CTX-002（出力スキーマ + 出力形式 PMT-005〜008）→ CTX-003（データ宣言 PMT-009）。固定で削らない
- contents: 委譲プロンプト（PMT-010〜012）に、ガードを通した CTX-004〜007 の値を差し込む → 再試行なら CTX-008（PMT-013〜016）
信頼できない CTX-004 / 006 / 007 は必ず contents 側に置き、区切り記号で囲む（CG-001・CG-002）。
ブロックごとの上限（5 章）で打ち切り、それでも入力の合計が予算を超えたら 6 章の順位で削る。削ったことは truncations に残す。"""

import json
from dataclasses import dataclass, field

from pydantic import BaseModel

from ..config import get_settings
from . import prompts
from .guards import DELIMITER, clean_value, filter_candidate, guard, wrap
from .llm import AgentId, estimate_tokens

# 5 章: コンテキスト長に対する上限
CTX_LIMITS = {"CTX-001": 0.06, "CTX-002": 0.05, "CTX-003": 0.02, "CTX-004": 0.06,
              "CTX-005": 0.08, "CTX-006": 0.20, "CTX-007": 0.28, "CTX-008": 0.05}
INPUT_RATIO = 0.80  # 入力の合計（出力 15 %・予備 5 % を除く。5 章の検算）
FIXED = ("CTX-001", "CTX-002", "CTX-003")
UNTRUSTED = ("CTX-004", "CTX-006", "CTX-007")

ROLE = {"AG-001": "PMT-001", "AG-002": "PMT-002", "AG-003": "PMT-003", "AG-004": "PMT-004"}
OUTPUT_FORMAT = {"AG-001": "PMT-005", "AG-002": "PMT-006", "AG-003": "PMT-007", "AG-004": "PMT-008"}
RETRY = {"AG-001": "PMT-013", "AG-002": "PMT-014", "AG-003": "PMT-015", "AG-004": "PMT-016"}


class ContextError(ValueError):
    pass


@dataclass
class Truncation:
    ctx_id: str
    unit: str  # tokens | items
    before: int
    after: int


@dataclass
class BuiltContext:
    agent_id: str
    system: str
    contents: str
    order: list[str]  # 実際に並んだ順（検証とテスト用）
    truncations: list[Truncation] = field(default_factory=list)

    @property
    def input_tokens(self) -> int:
        return estimate_tokens(self.system) + estimate_tokens(self.contents)


def context_tokens() -> int:
    return get_settings().agent_context_tokens


def cap(ctx_id: str) -> int:
    return int(context_tokens() * CTX_LIMITS[ctx_id])


def check_order(order: list[str]) -> None:
    """CG-002: 固定の 3 ブロックが先頭に順に並び、信頼できないブロックはその後ろにだけ現れる。CTX-008 は最後。"""
    if tuple(order[:3]) != FIXED:
        raise ContextError(f"CTX-001 to 003 are not at the start: {order}")
    if any(c in FIXED for c in order[3:]):
        raise ContextError(f"Fixed blocks are mixed into the variable part: {order}")
    if "CTX-008" in order and order[-1] != "CTX-008":
        raise ContextError(f"CTX-008 is not at the end: {order}")


def _system(agent_id: AgentId, schema: type[BaseModel]) -> str:
    """CTX-001〜003。可変の値を入れない（キャッシュ境界 1 より前。4-3）。"""
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False, sort_keys=True)
    blocks = {
        "CTX-001": prompts.render(ROLE[agent_id]),
        "CTX-002": f"Output schema:\n{schema_json}\n\n{prompts.render(OUTPUT_FORMAT[agent_id])}",
        "CTX-003": prompts.render("PMT-009", delimiter=DELIMITER),
    }
    for ctx_id, text in blocks.items():
        if estimate_tokens(text) > cap(ctx_id):  # 削らないブロック（6 章）。収まらないのは設定かプロンプトの誤り
            raise ContextError(f"{ctx_id} exceeds its limit ({estimate_tokens(text)} > {cap(ctx_id)})")
    return "\n\n".join(blocks.values())


def _lines(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items)


@dataclass
class _Parts:
    """contents の材料。_fit が 6 章の順位でここを削る。"""
    candidates: list[dict] = field(default_factory=list)  # CTX-007（filter_candidate 済み）
    candidates_total: int = 0
    violations: list[str] = field(default_factory=list)  # CTX-008（古い順）
    free_text: str = ""  # CTX-006 の元の文
    free_text_cap: int = 0
    human_roles: list[dict] | None = None  # CTX-004（AG-003）
    truncations: list[Truncation] = field(default_factory=list)


def _free_text(p: _Parts) -> str:
    g = guard(p.free_text, p.free_text_cap)
    if g.truncated and not any(t.ctx_id == "CTX-006" for t in p.truncations):
        p.truncations.append(Truncation("CTX-006", "tokens", g.original_tokens, g.kept_tokens))
    return g.text


def _candidates_block(p: _Parts) -> str:
    """CTX-007: 並びは呼び出し側（TOOL-002）の決定的な順のまま、上限に収まる件数だけ入れる。"""
    lines, used = [], 0
    for c in p.candidates:
        line = json.dumps(c, ensure_ascii=False, sort_keys=True)
        if used + estimate_tokens(line) + 1 > cap("CTX-007"):
            break
        lines.append(line)
        used += estimate_tokens(line) + 1
    if len(lines) < len(p.candidates):
        p.truncations.append(Truncation("CTX-007", "items", len(p.candidates), len(lines)))
        p.candidates = p.candidates[: len(lines)]
    return "\n".join(lines)


def _violations_block(p: _Parts) -> str:
    """CTX-008: 違反項目だけ（前回の出力は入れない。CG-007）。上限を超えたら古いものから落とす。"""
    kept = list(p.violations)
    while kept and estimate_tokens(_lines(kept)) > cap("CTX-008"):
        kept.pop(0)
    if len(kept) < len(p.violations):
        p.truncations.append(Truncation("CTX-008", "items", len(p.violations), len(kept)))
        p.violations = kept
    return _lines(kept)


def _shrink(p: _Parts) -> Truncation | None:
    """入力の合計が予算を超えたときの削り方（6 章の順位）。削れなければ None。"""
    if p.candidates:
        before = len(p.candidates)
        p.candidates = p.candidates[:-1]
        return Truncation("CTX-007", "items", before, len(p.candidates))
    if len(p.violations) > 1:
        before = len(p.violations)
        p.violations = p.violations[1:]
        return Truncation("CTX-008", "items", before, len(p.violations))
    if p.free_text and p.free_text_cap > 1:
        before = p.free_text_cap
        p.free_text_cap //= 2
        return Truncation("CTX-006", "tokens", before, p.free_text_cap)
    if p.human_roles:
        before = len(p.human_roles)
        p.human_roles = []
        return Truncation("CTX-004", "items", before, 0)
    return None


def _fit(agent_id: AgentId, system: str, p: _Parts, render) -> BuiltContext:
    """render(p) -> (contents, order) を、入力の合計が予算に収まるまで削りながら組み立てる。"""
    budget = int(context_tokens() * INPUT_RATIO)
    while True:
        contents, order = render(p)
        order = [*FIXED, *order]
        check_order(order)
        ctx = BuiltContext(agent_id, system, contents, order, list(p.truncations))
        if ctx.input_tokens <= budget:
            return ctx
        t = _shrink(p)
        if t is None:
            raise ContextError(f"Input does not fit in the budget ({ctx.input_tokens} > {budget})")
        p.truncations.append(t)


def _retry(agent_id: AgentId, p: _Parts, **extra: object) -> list[tuple[str, str]]:
    if not p.violations:
        return []
    return [("CTX-008", prompts.render(RETRY[agent_id], violations=_violations_block(p), **extra))]


def _join(parts: list[tuple[str, str]]) -> tuple[str, list[str]]:
    return "\n\n".join(text for _, text in parts), [c for c, _ in parts]


# ---------------------------------------------------------------- エージェント別（context-templates.md）


def build_ag002(*, requirement_text: str, phases: list[dict], max_tasks: int, schema: type[BaseModel], violations: list[str] | None = None) -> BuiltContext:
    """AG-002: CTX-001〜003 → CTX-004（工程）→ CTX-006（依頼文）→ CTX-008。予算額と候補は入れない。"""
    system = _system("AG-002", schema)
    p = _Parts(violations=list(violations or []), free_text=requirement_text, free_text_cap=cap("CTX-006"))
    phases_text = wrap(guard(_lines([f"{clean_value(x['key'])}: {clean_value(x['title'])}" for x in phases]), cap("CTX-004")).text)

    def render(p: _Parts):
        body = prompts.render("PMT-010", phases=phases_text, max_tasks=max_tasks, delimiter=DELIMITER, requirement_text=_free_text(p))
        return _join([("CTX-004", body), *_retry("AG-002", p)])

    return _fit("AG-002", system, p, render)


def build_ag003(*, budget_amount: str, human_roles: list[dict], tasks: list[dict], candidates: list[dict], schema: type[BaseModel],
                violations: list[str] | None = None, excess_amount: str = "0") -> BuiltContext:
    """AG-003: 全ブロックを使う。CTX-005（予算額・候補の件数）→ CTX-004（人間の役割）→ CTX-006（タスク）→ CTX-007（候補）→ CTX-008。"""
    system = _system("AG-003", schema)
    task_lines = _lines([f"{clean_value(t['seq'])}. [{clean_value(t['phase'])}] {clean_value(t['title'])}" for t in tasks])
    p = _Parts(candidates=[filter_candidate(c) for c in candidates], candidates_total=len(candidates),
               violations=list(violations or []), free_text=task_lines, free_text_cap=cap("CTX-006"), human_roles=list(human_roles))

    def render(p: _Parts):
        roles = _lines([", ".join(f"{k}={clean_value(v)}" for k, v in r.items()) for r in (p.human_roles or [])]) or "- None specified"
        roles_text = wrap(guard(roles, cap("CTX-004")).text)
        cands = _candidates_block(p)
        # 6 章: CTX-007 を減らしたら、候補が全部ではないことを構造化された値で CTX-005 に入れる
        counts = f"Total candidates: {p.candidates_total} / shown: {len(p.candidates)}"
        body = prompts.render("PMT-011", budget_amount=budget_amount, human_roles=roles_text, delimiter=DELIMITER, tasks=_free_text(p), candidates=cands)
        return _join([("CTX-005", counts), ("CTX-006", body), *_retry("AG-003", p, excess_amount=excess_amount)])

    return _fit("AG-003", system, p, render)


def build_ag004(*, task_record: dict, claims: list[dict], schema: type[BaseModel], violations: list[str] | None = None) -> BuiltContext:
    """AG-004: CTX-005（対象タスクの記録）→ CTX-006（主張の要約）→ CTX-008。policy は入れない。"""
    system = _system("AG-004", schema)
    record = json.dumps(task_record, ensure_ascii=False, sort_keys=True)
    claim_lines = _lines([f"{clean_value(c['party'])}: {clean_value(c['summary'])}" for c in claims])
    p = _Parts(violations=list(violations or []), free_text=claim_lines, free_text_cap=cap("CTX-006"))

    def render(p: _Parts):
        body = prompts.render("PMT-012", delimiter=DELIMITER, task_record=record, claims=_free_text(p))
        return _join([("CTX-006", body), *_retry("AG-004", p)])

    return _fit("AG-004", system, p, render)


def build_ag001(*, state: dict, texts: list[str], schema: type[BaseModel], violations: list[str] | None = None) -> BuiltContext:
    """AG-001: CTX-005（案件の状態・件数・予算額）→ CTX-006（委譲先が返した自由文。tasks[].title など）→ CTX-008。
    policy・ENS の候補・金額と送金先は入れない（context-templates AG-001）。"""
    system = _system("AG-001", schema)
    p = _Parts(violations=list(violations or []), free_text=_lines(texts), free_text_cap=cap("CTX-006"))

    def render(p: _Parts):
        state_text = "Current step and case status:\n" + json.dumps(state, ensure_ascii=False, sort_keys=True)
        return _join([("CTX-005", state_text), ("CTX-006", wrap(_free_text(p))), *_retry("AG-001", p)])

    return _fit("AG-001", system, p, render)
