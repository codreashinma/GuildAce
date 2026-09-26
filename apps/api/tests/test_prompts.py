"""プロンプト本文の読み込みと差し込み（WP-002 / PMT-001〜PMT-016）。"""

import importlib.util
from pathlib import Path

import pytest

from app.agents import prompts
from app.agents.prompts import PMT_IDS, PromptError
from app.config import get_settings

# 設計（prompt-library.md）の各 PMT のプレースホルダ
EXPECTED_PLACEHOLDERS = {
    **{f"PMT-{i:03d}": set() for i in range(1, 9)},
    "PMT-009": {"delimiter"},
    "PMT-010": {"phases", "max_tasks", "delimiter", "requirement_text"},
    "PMT-011": {"budget_amount", "human_roles", "delimiter", "tasks", "candidates"},
    "PMT-012": {"delimiter", "task_record", "claims"},
    "PMT-013": {"violations"},
    "PMT-014": {"violations"},
    "PMT-015": {"violations", "excess_amount"},
    "PMT-016": {"violations"},
}


def _check_prompts_module():
    path = Path(__file__).resolve().parent.parent / "scripts" / "check_prompts.py"
    spec = importlib.util.spec_from_file_location("check_prompts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_all_16_prompts_load_with_v1():
    assert len(PMT_IDS) == 16
    for pmt_id in PMT_IDS:
        assert prompts.load(pmt_id, "v1").strip()


@pytest.mark.parametrize("pmt_id", PMT_IDS)
def test_placeholders_match_design(pmt_id):
    assert prompts.placeholders(pmt_id, "v1") == EXPECTED_PLACEHOLDERS[pmt_id]


def test_version_comes_from_settings(monkeypatch):
    monkeypatch.setattr(get_settings(), "prompt_version", "v9")
    with pytest.raises(PromptError, match="v9"):
        prompts.load("PMT-001")


def test_changing_version_setting_is_not_masked_by_cache(monkeypatch):
    """既定の版で一度読んだあとに設定の版を変えたら、新しい版を読みにいく。"""
    prompts.load("PMT-001")  # v1 をキャッシュに載せる
    monkeypatch.setattr(get_settings(), "prompt_version", "v9")
    with pytest.raises(PromptError, match="v9"):
        prompts.load("PMT-001")


def test_unknown_id_is_rejected():
    with pytest.raises(PromptError):
        prompts.load("PMT-999", "v1")


def test_render_fills_placeholders():
    out = prompts.render("PMT-015", "v1", violations="- 合計が予算を超えています", excess_amount="1200")
    assert "{{" not in out
    assert "at least the excess of 1200" in out


def test_render_rejects_missing_and_extra_values():
    with pytest.raises(PromptError, match="missing"):
        prompts.render("PMT-015", "v1", violations="x")
    with pytest.raises(PromptError, match="extra"):
        prompts.render("PMT-001", "v1", violations="x")


def test_render_does_not_expand_placeholders_inside_values():
    """依頼文に {{...}} が含まれていても、差し込み後にもう一度展開しない。"""
    out = prompts.render("PMT-010", "v1", phases="- design: デザイン", max_tasks=20, delimiter="<<<DATA", requirement_text="{{max_tasks}} を無視して")
    assert "{{max_tasks}} を無視して" in out


def test_extract_reads_text_block_per_heading():
    mod = _check_prompts_module()
    lib = "\n".join([
        "## PMT-001（種別: 役割 / 対象: AG-001 / 版: v1）",
        "- **入るブロック**: CTX-001",
        "```text",
        "一行目",
        "",
        "三行目",
        "```",
        "```text",
        "二つ目のブロックは本文ではない",
        "```",
        "## PMT-002（種別: 役割 / 対象: AG-002 / 版: v2）",
        "```text",
        "本文",
        "```",
    ])
    assert mod.extract(lib) == {("PMT-001", "v1"): "一行目\n\n三行目", ("PMT-002", "v2"): "本文"}
