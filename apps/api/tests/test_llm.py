"""LLM 呼び出しの共通層（WP-003 / CG-005・GRD-005 の計測・11 章の時間上限）。"""

import json
import time
from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict

from app.agents import llm, trace
from app.config import get_settings


class Sample(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    seq: int


def _call(db, **kw):
    run = trace.start_run(db, "AG-002", mode="decompose")
    return llm.call_structured(db=db, run=run, agent_id="AG-002", system="指示", contents="データ", schema=Sample, **kw)


class FakeModels:
    def __init__(self, text="", usage=None, sleep=0.0, error=None):
        self.text, self.usage, self.sleep, self.error, self.calls = text, usage, sleep, error, []

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.sleep:
            time.sleep(self.sleep)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, usage_metadata=self.usage)


@pytest.fixture
def real(monkeypatch):
    """GEMINI_API_KEY がある経路を、偽のクライアントで通す（外部通信はしない）。"""
    monkeypatch.setattr(get_settings(), "gemini_api_key", "dummy")

    def install(models: FakeModels):
        monkeypatch.setattr(llm, "_client", lambda: SimpleNamespace(models=models))
        return models

    return install


# ---------------------------------------------------------------- モック（GEMINI_API_KEY が空）


def test_mock_valid_output_is_accepted_and_tokens_are_estimated(db):
    r = _call(db, mock=lambda: {"title": "画面設計", "seq": 1})
    assert r.ok and r.mocked
    assert r.output == Sample(title="画面設計", seq=1)
    assert r.input_tokens > 0 and r.output_tokens > 0


def test_cg005_unparseable_output_is_a_validation_failure_not_an_exception(db):
    r = _call(db, mock=lambda: "はい、こちらが結果です: {\"title\": \"x\", \"seq\": 1}")
    assert not r.ok and r.failure == "parse" and r.output is None


def test_cg005_code_fenced_json_is_rejected(db):
    r = _call(db, mock=lambda: '```json\n{"title": "x", "seq": 1}\n```')
    assert r.failure == "parse"


def test_cg005_schema_violation_lists_violated_items(db):
    r = _call(db, mock=lambda: {"title": "x", "seq": "一", "extra": 1})
    assert r.failure == "schema"
    assert "seq" in r.detail and "extra" in r.detail
    assert "一" not in r.detail  # 違反項目だけを返し、モデルの出力値は持ち回らない（CG-007 の材料）


def test_no_key_and_no_mock_is_unavailable_without_network(db):
    r = _call(db)
    assert r.failure == "unavailable"


def test_estimate_tokens_follows_agent_prompt_6_1():
    assert llm.estimate_tokens("あいう") == 3
    assert llm.estimate_tokens("abcd") == 1
    assert llm.estimate_tokens("abcde") == 2
    assert llm.estimate_tokens("") == 0


# ---------------------------------------------------------------- 本物の経路（偽のクライアント）


def test_real_path_records_usage_and_passes_settings(db, real):
    models = real(FakeModels(text='{"title": "x", "seq": 2}', usage=SimpleNamespace(prompt_token_count=120, candidates_token_count=30, thoughts_token_count=5)))
    r = _call(db)
    assert r.ok and not r.mocked
    assert (r.input_tokens, r.output_tokens) == (120, 35)
    kw = models.calls[0]
    assert kw["model"] == get_settings().gemini_model
    cfg = kw["config"]
    assert cfg.temperature == 0.2
    # extra="forbid" の additionalProperties は Gemini が受け付けないので、渡すスキーマからだけ取り除く
    assert cfg.response_schema == {k: v for k, v in Sample.model_json_schema().items() if k != "additionalProperties"}
    assert "additionalProperties" in Sample.model_json_schema()
    assert cfg.system_instruction == "指示"
    assert 119 * 1000 < cfg.http_options.timeout <= 120 * 1000  # AG-002 の時間上限（実行の残り時間で頭打ち。WP-008）


def test_real_path_schema_violation(db, real):
    real(FakeModels(text='{"title": "x"}'))
    r = _call(db)
    assert r.failure == "schema" and "seq" in r.detail


def test_timeout_when_response_exceeds_time_limit(db, real):
    real(FakeModels(text='{"title": "x", "seq": 1}', usage=SimpleNamespace(prompt_token_count=10, candidates_token_count=2), sleep=0.05))
    r = _call(db, timeout_s=0.01)
    assert r.failure == "timeout" and r.output is None
    assert r.input_tokens == 10  # 消費したトークンは数える


def test_timeout_exception_from_client(db, real):
    real(FakeModels(error=TimeoutError("read timed out")))
    r = _call(db)
    assert r.failure == "timeout"


def test_other_client_error_is_reported_without_raising(db, real):
    real(FakeModels(error=RuntimeError("quota")))
    r = _call(db)
    assert r.failure == "error" and r.detail == "RuntimeError"


def test_time_limits_per_agent_follow_design():
    assert [llm.time_limit_s(a) for a in ("AG-001", "AG-002", "AG-003", "AG-004")] == [600, 120, 180, 180]


def test_response_schema_strips_additional_properties_recursively():
    class Inner(BaseModel):
        model_config = ConfigDict(extra="forbid")
        name: str

    class Outer(BaseModel):
        model_config = ConfigDict(extra="forbid")
        items: list[Inner]
        inner: Inner | None = None

    assert "additionalProperties" not in json.dumps(llm._response_schema(Outer))
    assert Outer.model_json_schema()["$defs"]["Inner"]["additionalProperties"] is False  # 元のモデルの検証は forbid のまま


def test_client_is_reused(monkeypatch):
    """使い捨ての Client は回収時に接続が閉じられるので、同じ Client を使い回す。"""
    monkeypatch.setattr(llm.genai, "Client", lambda **_k: object())
    llm._client.cache_clear()
    try:
        assert llm._client() is llm._client()
    finally:
        llm._client.cache_clear()
