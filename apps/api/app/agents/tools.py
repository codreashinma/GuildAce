"""エージェントのツールの実行基盤（WP-006 / agent-orchestration 6-2・8 章）。
- ツールの登録簿（TOOL-ID・名前・副作用の種類）と、エージェントごとの許可リスト（GRD-001）をここで持つ
- 許可されていない呼び出しは実行せずに拒否し、記録する。権限をプロンプトの文言ではなくここで縛る（CG-006）
- 呼び出しはすべて agent_tool_calls に記録する（trace.record_tool_call）
- 呼び出しの前にキルスイッチを確かめ、止まっていれば実装を呼ばずに中断する（GRD-007。WP-007）
- 参照と可逆のツールは失敗時に 3 回まで試す。不可逆のツールは再試行しない（agent-orchestration 6-2・10 章）
ツールの実装は各モジュール（tool_read.py など）が register で登録する。人間性の検証（World）に書くツールは登録しない（GRD-008）。"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy.orm import Session

from ..models import AgentRun
from . import control, trace

log = logging.getLogger(__name__)

Effect = Literal["read", "reversible", "irreversible"]
MAX_ATTEMPTS = {"read": 3, "reversible": 3, "irreversible": 1}


@dataclass(frozen=True)
class ToolDef:
    tool_id: str
    name: str
    effect: Effect


# 6-2 ツール一覧
TOOLS: dict[str, ToolDef] = {t.tool_id: t for t in (
    ToolDef("TOOL-001", "read_project_context", "read"),
    ToolDef("TOOL-002", "search_agents_by_ens", "read"),
    ToolDef("TOOL-003", "read_dispute_record", "read"),
    ToolDef("TOOL-004", "save_task_plan", "reversible"),
    ToolDef("TOOL-005", "save_team_proposal", "reversible"),
    ToolDef("TOOL-006", "update_task_progress", "reversible"),
    ToolDef("TOOL-007", "save_dispute_summary", "reversible"),
    ToolDef("TOOL-008", "request_requester_reconfirmation", "reversible"),
    ToolDef("TOOL-009", "execute_escrow_funding", "irreversible"),
)}

# GRD-001: 6-2 の「呼べるエージェント」。AG-002 は 0 件
ALLOWED: dict[str, frozenset[str]] = {
    "AG-001": frozenset({"TOOL-001", "TOOL-004", "TOOL-005", "TOOL-006", "TOOL-007", "TOOL-008", "TOOL-009"}),
    "AG-002": frozenset(),
    "AG-003": frozenset({"TOOL-001", "TOOL-002"}),
    "AG-004": frozenset({"TOOL-001", "TOOL-003"}),
}


@dataclass
class ToolContext:
    """ツールの実装に渡す文脈。実行（run）に結び付いた案件・紛争の外を読ませないために使う。"""
    db: Session
    run: AgentRun


@dataclass
class ToolResult:
    ok: bool
    value: Any = None
    error: str | None = None
    denied: bool = False
    stopped: bool = False  # GRD-007 で中断した
    attempts: int = 0


class ToolError(Exception):
    """ツールの実装が、入力が不正・対象の外などの理由で実行を断るときに投げる（再試行しない）。"""


ToolImpl = Callable[..., Any]
_IMPLS: dict[str, ToolImpl] = {}


def register(tool_id: str) -> Callable[[ToolImpl], ToolImpl]:
    if tool_id not in TOOLS:
        raise ValueError(f"Unknown tool: {tool_id}")

    def deco(fn: ToolImpl) -> ToolImpl:
        _IMPLS[tool_id] = fn
        return fn

    return deco


def is_allowed(agent_id: str, tool_id: str) -> bool:
    return tool_id in ALLOWED.get(agent_id, frozenset())


def call_tool(db: Session, run: AgentRun, tool_id: str, **args: Any) -> ToolResult:
    """エージェントの実行 run からツールを呼ぶ。許可の判定・再試行・記録をここで行う。"""
    started = time.monotonic()

    def done(result: ToolResult) -> ToolResult:
        trace.record_tool_call(db, run, tool_id, allowed=not result.denied, ok=result.ok,
                               duration_ms=int((time.monotonic() - started) * 1000), error=result.error)
        return result

    stop = control.state_for_run(db, run)
    if stop.stopped:  # GRD-007: 次のツール呼び出しの前に中断する
        log.warning("停止中のためツール呼び出しを中断しました（%s → %s、%s）", run.agent_id, tool_id, stop.scope)
        return done(ToolResult(False, error=f"Stopped ({stop.scope}: {stop.reason})", stopped=True))
    tool = TOOLS.get(tool_id)
    if tool is None:
        return done(ToolResult(False, error=f"Unknown tool: {tool_id}", denied=True))
    if not is_allowed(run.agent_id, tool_id):  # GRD-001: 実行せずに拒否
        log.warning("許可されていないツール呼び出しを拒否しました（%s → %s）", run.agent_id, tool_id)
        return done(ToolResult(False, error=f"{run.agent_id} is not allowed to call {tool_id} ({tool.name})", denied=True))
    impl = _IMPLS.get(tool_id)
    if impl is None:
        return done(ToolResult(False, error=f"{tool_id} ({tool.name}) is not implemented"))

    last_error = ""
    for attempt in range(1, MAX_ATTEMPTS[tool.effect] + 1):
        try:
            return done(ToolResult(True, impl(ToolContext(db, run), **args), attempts=attempt))
        except ToolError as e:
            return done(ToolResult(False, error=str(e), attempts=attempt))
        except Exception as e:  # noqa: BLE001
            db.rollback()
            last_error = f"{type(e).__name__}: {e}"
            log.warning("ツールの実行に失敗しました（%s %s 回目）: %s", tool_id, attempt, type(e).__name__)
    return done(ToolResult(False, error=last_error, attempts=MAX_ATTEMPTS[tool.effect]))
