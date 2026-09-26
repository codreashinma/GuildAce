"""エージェントから Gemini を呼ぶ共通層（WP-003）。
- 出力は構造化（JSON）でだけ受け取り、パースとスキーマ検証をこちらで行う。合わない応答は出力とみなさず「検証失敗」として返す（CG-005、agent-context 9 章）
- 入力・出力のトークン数を返す（GRD-005 のコスト計測に使う）
- エージェントごとの時間上限で打ち切る（agent-orchestration 11 章）
- 呼ぶ前に反復・時間・コストの上限（limits.check_before_llm。WP-008 / GRD-005）を確かめ、達していれば呼ばずに「limit」で返す
GEMINI_API_KEY が無い場合は、呼び出し側が渡した決定的な応答（mock）を同じ検証に通す。既存の services/gemini.py とは独立している。"""

import json
import logging
import time
from collections.abc import Callable
from functools import lru_cache
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AgentRun
from . import limits
from .limits import LimitHit

log = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
Failure = Literal["parse", "schema", "timeout", "error", "unavailable", "limit"]
AgentId = Literal["AG-001", "AG-002", "AG-003", "AG-004"]


@dataclass
class LLMResult(Generic[T]):
    output: T | None
    failure: Failure | None = None
    detail: str = ""  # 失敗の理由。検証失敗なら違反した項目（CTX-008 の材料。モデルの出力そのものは入れない）
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_s: float = 0.0
    mocked: bool = False
    limit_hit: LimitHit | None = None  # failure == "limit" のときの理由（エスカレーション先の判断に使う。12-3）

    @property
    def ok(self) -> bool:
        return self.failure is None


def estimate_tokens(text: str) -> int:
    """トークン数の概算（agent-prompt 6-1 と同じ数え方: 全角 1 文字 ≒ 1、ASCII 4 文字 ≒ 1）。モック時に使う。"""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return (len(text) - ascii_chars) + -(-ascii_chars // 4)


def time_limit_s(agent_id: AgentId) -> float:
    return limits.run_time_limit_s(agent_id)


@lru_cache(maxsize=1)
def _client() -> genai.Client:
    """Client は保持しておく。使い捨てにすると回収時に接続が閉じられ、送信前に RuntimeError になる。"""
    return genai.Client(api_key=get_settings().gemini_api_key)


def _strip_additional_properties(node):
    """Gemini の response_schema は additionalProperties を受け付けない（400）ので、渡すスキーマからだけ取り除く。
    余分な項目は _validate が extra="forbid" のモデルで弾く。"""
    if isinstance(node, dict):
        return {k: _strip_additional_properties(v) for k, v in node.items() if k != "additionalProperties"}
    if isinstance(node, list):
        return [_strip_additional_properties(v) for v in node]
    return node


def _response_schema(schema: type[BaseModel]) -> dict:
    return _strip_additional_properties(schema.model_json_schema())


def _validate(raw: str, schema: type[T]) -> tuple[T | None, Failure | None, str]:
    """JSON として読み、スキーマで検証する。前置き・コードブロックの囲みは受け付けない（PMT-005〜008）。"""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as e:
        return None, "parse", f"JSON として読めません（{e.msg if hasattr(e, 'msg') else type(e).__name__}）"
    try:
        return schema.model_validate(data), None, ""
    except ValidationError as e:
        items = [f"{'.'.join(str(x) for x in err['loc']) or '(全体)'}: {err['msg']}" for err in e.errors()]
        return None, "schema", "\n".join(items)


def call_structured(
    *,
    db: Session,
    run: AgentRun,
    agent_id: AgentId,
    system: str,
    contents: str,
    schema: type[T],
    mock: Callable[[], str | dict] | None = None,
    timeout_s: float | None = None,
) -> LLMResult[T]:
    """system（CTX-001〜003）と contents（CTX-004〜008）を渡し、schema に合う出力だけを返す。
    run はこの呼び出しを記録する実行（trace.start_run）。上限の判定に使う。"""
    s = get_settings()
    # GRD-005 / 11 章: 上限に達していたらモデルを呼ばない（モックも呼ばない）
    hit = limits.check_before_llm(db, run)
    if hit is not None:
        log.warning("LLM を呼ばずに打ち切りました（%s %s）", agent_id, hit.detail)
        return LLMResult(None, "limit", hit.detail, mocked=not s.gemini_enabled, limit_hit=hit)
    # 1 回の呼び出しの待ち時間は、実行に残っている時間を超えない
    limit = min(timeout_s if timeout_s is not None else time_limit_s(agent_id), limits.remaining_s(run))
    started = time.monotonic()

    if not s.gemini_enabled:
        if mock is None:
            return LLMResult(None, "unavailable", "GEMINI_API_KEY が無く、モックの応答も渡されていません", mocked=True)
        raw = mock()
        raw = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
        out, failure, detail = _validate(raw, schema)
        return LLMResult(out, failure, detail, estimate_tokens(system + contents), estimate_tokens(raw), time.monotonic() - started, mocked=True)

    try:
        resp = _client().models.generate_content(
            model=s.gemini_model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_schema=_response_schema(schema),
                temperature=s.agent_temperature,
                http_options=types.HttpOptions(timeout=max(1, int(limit * 1000))),
            ),
        )
    except Exception as e:  # noqa: BLE001
        elapsed = time.monotonic() - started
        kind: Failure = "timeout" if ("timeout" in type(e).__name__.lower() or elapsed >= limit) else "error"
        log.warning("LLM 呼び出しに失敗しました（%s %s: %s）", agent_id, kind, type(e).__name__)
        return LLMResult(None, kind, type(e).__name__, elapsed_s=elapsed)

    elapsed = time.monotonic() - started
    usage = getattr(resp, "usage_metadata", None)
    in_tok = int(getattr(usage, "prompt_token_count", 0) or 0)
    out_tok = int(getattr(usage, "candidates_token_count", 0) or 0) + int(getattr(usage, "thoughts_token_count", 0) or 0)
    if elapsed > limit:
        # 時間上限を超えた応答は使わない（トークンは消費済みなので数える）
        return LLMResult(None, "timeout", f"{elapsed:.1f} 秒（上限 {limit:.0f} 秒）", in_tok, out_tok, elapsed)
    out, failure, detail = _validate(resp.text or "", schema)
    return LLMResult(out, failure, detail, in_tok, out_tok, elapsed)
