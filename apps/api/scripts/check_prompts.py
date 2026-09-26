"""プロンプト本文（PMT）の正本との一致確認（エージェント実装計画 WP-002 / DEC-005）。

正本は vault の agent-prompt/prompt-library.md（日本語）。公開環境からは読めないので、その写しを
app/agents/prompts/ja/<PMT-ID>-<版>.txt としてリポジトリに置き、このスクリプトで食い違いを検出する。
実行時に使う本文は app/agents/prompts/<PMT-ID>-<版>.txt（英訳。画面に出る出力を英語にするため）。
英訳は正本と文面では突き合わせられないので、同じ PMT-ID・版がそろっていることと、プレースホルダの集合が
日本語の写しと一致することを確かめる。

  python scripts/check_prompts.py            # 一致を確認（食い違いがあれば終了コード 1）
  python scripts/check_prompts.py --write    # 正本からファイルを書き出す（版を足したときに使う）

正本の場所は環境変数 PROMPT_LIBRARY で変えられる。"""

import os
import re
import sys
from pathlib import Path

DEFAULT_LIBRARY = "/mnt/c/second-brain/ethglobal_hackathon/docs/agent-prompt/prompt-library.md"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "app" / "agents" / "prompts"
JA_DIR = PROMPT_DIR / "ja"  # 正本（日本語）の写し

_HEADING = re.compile(r"^## (PMT-\d{3})（.*版: (v\d+)）\s*$")
_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


def extract(library: str) -> dict[tuple[str, str], str]:
    """prompt-library.md から {(PMT-ID, 版): 本文} を取り出す。本文は各節の最初の ```text ブロック。"""
    out: dict[tuple[str, str], str] = {}
    current: tuple[str, str] | None = None
    body: list[str] | None = None
    for line in library.splitlines():
        m = _HEADING.match(line)
        if m:
            current, body = (m.group(1), m.group(2)), None
            continue
        if current is None or current in out:
            continue
        if body is None and line.strip() == "```text":
            body = []
        elif body is not None and line.strip() == "```":
            out[current] = "\n".join(body)
            body = None
        elif body is not None:
            body.append(line)
    return out


def file_path(pmt_id: str, version: str) -> Path:
    """正本の写し（日本語）"""
    return JA_DIR / f"{pmt_id}-{version}.txt"


def english_path(pmt_id: str, version: str) -> Path:
    """実行時に使う英訳"""
    return PROMPT_DIR / f"{pmt_id}-{version}.txt"


def check_english() -> list[str]:
    """英訳が日本語の写しと 1 対 1 にそろい、プレースホルダの集合が同じであることを確かめる。"""
    problems: list[str] = []
    ja = {p.name: p for p in JA_DIR.glob("PMT-*.txt")}
    en = {p.name: p for p in PROMPT_DIR.glob("PMT-*.txt")}
    for name in sorted(ja.keys() - en.keys()):
        problems.append(f"missing English  {name}")
    for name in sorted(en.keys() - ja.keys()):
        problems.append(f"no Japanese source  {name}")
    for name in sorted(ja.keys() & en.keys()):
        a = set(_PLACEHOLDER.findall(ja[name].read_text(encoding="utf-8")))
        b = set(_PLACEHOLDER.findall(en[name].read_text(encoding="utf-8")))
        if a != b:
            problems.append(f"placeholder mismatch  {name} (ja {sorted(a)} / en {sorted(b)})")
    return problems


def main(argv: list[str]) -> int:
    en_problems = check_english()
    for line in en_problems:
        print(line)
    lib_path = Path(os.environ.get("PROMPT_LIBRARY", DEFAULT_LIBRARY))
    if not lib_path.exists():
        print(f"Cannot read the source library (not available without the vault): {lib_path}")
        return 1 if en_problems else 2
    prompts = extract(lib_path.read_text(encoding="utf-8"))
    if "--write" in argv:
        JA_DIR.mkdir(parents=True, exist_ok=True)
        for (pmt_id, version), text in sorted(prompts.items()):
            file_path(pmt_id, version).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"Wrote {len(prompts)} prompts: {JA_DIR} (update the English translations in {PROMPT_DIR} as well)")
        return 0
    bad = len(en_problems)
    for (pmt_id, version), text in sorted(prompts.items()):
        p = file_path(pmt_id, version)
        if not p.exists():
            print(f"missing  {pmt_id} {version}")
            bad += 1
        elif p.read_text(encoding="utf-8").removesuffix("\n") != text:
            print(f"mismatch {pmt_id} {version}")
            bad += 1
    known = {file_path(*k).name for k in prompts}
    for p in sorted(JA_DIR.glob("PMT-*.txt")):
        if p.name not in known:
            print(f"not in source library  {p.name}")
            bad += 1
    if bad:
        print(f"{bad} discrepancies (source: {lib_path})")
        return 1
    print(f"OK: {len(prompts)} prompts match (source: {lib_path}), English translations are consistent")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
