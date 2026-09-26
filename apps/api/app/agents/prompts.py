"""プロンプト本文（PMT-001〜PMT-016）の読み込みと差し込み。
本文の正本は vault の agent-prompt/prompt-library.md（日本語）。リポジトリの prompts/ja/<PMT-ID>-<版>.txt はその写しで、
実行時に読む prompts/<PMT-ID>-<版>.txt はその英訳（画面に出る出力を英語にするため）。scripts/check_prompts.py で
写しと正本の一致、英訳と写しのプレースホルダの一致を確かめる（DEC-005）。本文をコードの中で言い換えない。"""

import re
from functools import lru_cache
from pathlib import Path

from ..config import get_settings

PROMPT_DIR = Path(__file__).parent / "prompts"
PMT_IDS = tuple(f"PMT-{i:03d}" for i in range(1, 17))

_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


class PromptError(ValueError):
    pass


def current_version() -> str:
    return get_settings().prompt_version


def load(pmt_id: str, version: str | None = None) -> str:
    """本文をそのまま返す（プレースホルダは差し込まない）。版を省略すると設定の版。"""
    return _load(pmt_id, version or current_version())


@lru_cache
def _load(pmt_id: str, v: str) -> str:
    if pmt_id not in PMT_IDS:
        raise PromptError(f"Unknown prompt ID: {pmt_id}")
    path = PROMPT_DIR / f"{pmt_id}-{v}.txt"
    if not path.exists():
        raise PromptError(f"{pmt_id} has no version {v}: {path.name}")
    return path.read_text(encoding="utf-8").removesuffix("\n")


def placeholders(pmt_id: str, version: str | None = None) -> set[str]:
    return set(_PLACEHOLDER.findall(load(pmt_id, version)))


def render(pmt_id: str, version: str | None = None, **values: object) -> str:
    """プレースホルダに値を差し込む。過不足があれば PromptError。
    差し込んだ値の中の {{...}} は展開しない（1 回の置換で済ませる）。"""
    text = load(pmt_id, version)
    need = set(_PLACEHOLDER.findall(text))
    missing, extra = need - values.keys(), values.keys() - need
    if missing or extra:
        raise PromptError(f"{pmt_id}: placeholder mismatch (missing {sorted(missing)} / extra {sorted(extra)})")
    return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]), text)
