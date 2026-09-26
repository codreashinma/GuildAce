"""プロンプト本文（PMT）の正本との一致確認（エージェント実装計画 WP-002 / DEC-005）。

正本は vault の agent-prompt/prompt-library.md。公開環境からは読めないので、本文を
app/agents/prompts/<PMT-ID>-<版>.txt としてリポジトリに置き、このスクリプトで食い違いを検出する。

  python scripts/check_prompts.py            # 一致を確認（食い違いがあれば終了コード 1）
  python scripts/check_prompts.py --write    # 正本からファイルを書き出す（版を足したときに使う）

正本の場所は環境変数 PROMPT_LIBRARY で変えられる。"""

import os
import re
import sys
from pathlib import Path

DEFAULT_LIBRARY = "/mnt/c/second-brain/ethglobal_hackathon/docs/agent-prompt/prompt-library.md"
PROMPT_DIR = Path(__file__).resolve().parent.parent / "app" / "agents" / "prompts"

_HEADING = re.compile(r"^## (PMT-\d{3})（.*版: (v\d+)）\s*$")


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
    return PROMPT_DIR / f"{pmt_id}-{version}.txt"


def main(argv: list[str]) -> int:
    lib_path = Path(os.environ.get("PROMPT_LIBRARY", DEFAULT_LIBRARY))
    if not lib_path.exists():
        print(f"正本が読めません（vault が無い環境では確認できません）: {lib_path}")
        return 2
    prompts = extract(lib_path.read_text(encoding="utf-8"))
    if "--write" in argv:
        PROMPT_DIR.mkdir(parents=True, exist_ok=True)
        for (pmt_id, version), text in sorted(prompts.items()):
            file_path(pmt_id, version).write_text(text + "\n", encoding="utf-8", newline="\n")
        print(f"{len(prompts)} 件を書き出しました: {PROMPT_DIR}")
        return 0
    bad = 0
    for (pmt_id, version), text in sorted(prompts.items()):
        p = file_path(pmt_id, version)
        if not p.exists():
            print(f"欠落  {pmt_id} {version}")
            bad += 1
        elif p.read_text(encoding="utf-8").removesuffix("\n") != text:
            print(f"不一致 {pmt_id} {version}")
            bad += 1
    known = {file_path(*k).name for k in prompts}
    for p in sorted(PROMPT_DIR.glob("PMT-*.txt")):
        if p.name not in known:
            print(f"正本に無い {p.name}")
            bad += 1
    if bad:
        print(f"食い違い {bad} 件（正本: {lib_path}）")
        return 1
    print(f"一致: {len(prompts)} 件（正本: {lib_path}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
