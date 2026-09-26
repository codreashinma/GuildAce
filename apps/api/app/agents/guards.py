"""信頼できない入力のガード（WP-004 / agent-context 7-2）。
依頼文・定義データの自由文・ENS の候補・紛争の主張（CTX-004 / 006 / 007）に、次の順で適用する。
  1. 正規化（CG-003）: NFKC、制御文字・ゼロ幅文字・双方向制御文字の除去、空白の圧縮
  2. 区切り記号の無害化（CG-001）: 内容に現れた <<< / >>> を全角に置き換える。NFKC が全角を ASCII に戻すので必ず 1 の後
  3. 長さの打ち切り（CG-004）: 末尾から打ち切り、打ち切ったことを返す（要約に置き換えない。agent-context 6 章）
  4. 区切り記号で囲む（CG-001）
区切り記号は DEC-006 で決めた <<<DATA>>>。PMT-009 は {{delimiter}} を 1 種類しか持たないため、開きと閉じに同じものを使う。"""

import re
import unicodedata
from dataclasses import dataclass

from .llm import estimate_tokens

DELIMITER = "<<<DATA>>>"

# CG-008: 候補（CTX-007）に入れてよい列。ENS の description などの自由文は入れない
CANDIDATE_FIELDS = ("ens_name", "domain", "reputation_score", "human_review_count")

_ZERO_WIDTH = "​‌‍⁠﻿᠎"
_BIDI = "‪‫‬‭‮⁦⁧⁨⁩‎‏؜"
_REMOVE = {ord(c): None for c in _ZERO_WIDTH + _BIDI}
_SPACES = re.compile(r"[ \t　]{2,}")
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass
class Guarded:
    text: str
    original_tokens: int  # 正規化後・打ち切り前
    kept_tokens: int

    @property
    def truncated(self) -> bool:
        return self.kept_tokens < self.original_tokens


def normalize(text: str) -> str:
    """CG-003: 見た目で区別できない文字や、区切り・指示の偽装に使われる文字を落とす。改行とタブは残す。"""
    text = unicodedata.normalize("NFKC", text).translate(_REMOVE)
    text = "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch) not in ("Cc", "Cf"))
    text = _SPACES.sub(" ", text.replace("\r\n", "\n").replace("\r", "\n"))
    return _BLANK_LINES.sub("\n\n", text).strip()


def neutralize(text: str) -> str:
    """CG-001: 内容に区切り記号が現れても区切りとして読めないようにする（文字数は変えない）。"""
    return text.replace("<<<", "＜＜＜").replace(">>>", "＞＞＞")


def truncate_tokens(text: str, max_tokens: int) -> str:
    """CG-004: 末尾から打ち切る。トークン数は llm.estimate_tokens と同じ数え方。"""
    if estimate_tokens(text) <= max_tokens:
        return text
    lo, hi = 0, len(text)
    while lo < hi:  # 上限に収まる最長の先頭部分
        mid = (lo + hi + 1) // 2
        if estimate_tokens(text[:mid]) <= max_tokens:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo]


def guard(text: str, max_tokens: int) -> Guarded:
    """正規化 → 無害化 → 打ち切り。区切りでは囲まない（wrap で囲む）。"""
    cleaned = neutralize(normalize(text))
    kept = truncate_tokens(cleaned, max_tokens)
    return Guarded(kept, estimate_tokens(cleaned), estimate_tokens(kept))


def wrap(text: str) -> str:
    """CG-001: 区切り記号で囲む。中身は guard を通したものであること。"""
    return f"{DELIMITER}\n{text}\n{DELIMITER}"


def clean_value(value: object) -> object:
    """構造化された値の中の文字列にも正規化と無害化をかける（打ち切りはしない）。"""
    if isinstance(value, str):
        return neutralize(normalize(value))
    return value


def filter_candidate(candidate: dict) -> dict:
    """CG-008: 構造化された属性だけを残す。"""
    return {k: clean_value(candidate.get(k)) for k in CANDIDATE_FIELDS}
