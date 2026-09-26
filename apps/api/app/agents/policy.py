"""PM Agent の定義データ（policy）（WP-009 / GRD-006・CTX-004 の入力、database-design「codrea.agent.policy のスキーマ」）。
置き場所は agents.policy（JSON）。ENS への書き出しは後回し（DEC-002）。
GRD-006: policy で変えられるのは workflow.phases と human_roles だけ。スキーマ外のキー（ツールの追加・上限の緩和・
World 検証の無効化などを狙うもの）は検証の段階で捨て、保存しない。policy はエージェントの権限・上限・World の検証を
決める経路（tools.ALLOWED・limits・各エンドポイントの World 検証）から読まれない。"""

import logging
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

log = logging.getLogger(__name__)

POLICY_VERSION = 1
PHASE_KEY = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"  # 工程キーは ENS の工程 subname に使う（ラベルと同じ形）
MAX_PHASES = 20  # 入力の大きさの上限（GRD-003 のタスク数の既定値にそろえた）
MAX_TITLE = 80

# DEC-002: policy が無い Agent の既定。工程キーは既存の role（services/gemini.py の PlannedTask.role）にそろえる
DEFAULT_PHASES = [
    ("designer", "Design"),
    ("frontend", "Frontend implementation"),
    ("backend", "Backend implementation"),
    ("field", "On-site work"),
    ("qa", "Test & deploy"),
]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="ignore")  # GRD-006: スキーマ外のキーは捨てる


class Phase(_Strict):
    key: str = Field(pattern=PHASE_KEY)
    title: str = Field(min_length=1, max_length=MAX_TITLE)


class Workflow(_Strict):
    phases: list[Phase] = Field(min_length=1, max_length=MAX_PHASES)

    @model_validator(mode="after")
    def _unique_keys(self):
        keys = [p.key for p in self.phases]
        dup = sorted({k for k in keys if keys.count(k) > 1})
        if dup:
            raise ValueError(f"Duplicate step keys: {', '.join(dup)}")
        return self


class HumanRole(_Strict):
    role: Literal["approver", "reviewer", "juror"]
    world_verified: bool
    min_count: int = Field(ge=1)  # 既定値は決めない（Q-007）。入力では必須


class Policy(_Strict):
    version: Literal[1]
    domain: str = Field(min_length=1, max_length=40)
    workflow: Workflow
    human_roles: list[HumanRole]


def default_policy(category: str) -> dict:
    """DEC-002 の既定。human_roles は人数の既定値が未決（Q-007）のため空にする。"""
    return {
        "version": POLICY_VERSION,
        "domain": category,
        "workflow": {"phases": [{"key": k, "title": t} for k, t in DEFAULT_PHASES]},
        "human_roles": [],
    }


def normalize(raw: dict) -> dict:
    """検証して、スキーマのキーだけを残した dict を返す。合わなければ ValidationError。"""
    return Policy.model_validate(raw).model_dump()


def effective(stored: dict | None, category: str) -> dict:
    """保存された policy、無ければ既定。保存された値が（手で書き換えられるなどして）合わなければ既定に戻す。"""
    if stored is None:
        return default_policy(category)
    try:
        return normalize(stored)
    except ValidationError:
        log.warning("保存された policy がスキーマに合わないため既定を使います")
        return default_policy(category)
