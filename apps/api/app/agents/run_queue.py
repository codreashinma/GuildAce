"""エージェントの実行の受け付け（WP-017 のランナーから分けた。WP-018）。
実行の要求を agent_runs の待ちの行（status = queued）にして、ランナーのスレッドを起こすだけ。
ルータ（/cases・/disputes）から呼ぶので、ルータを import するエージェントのモジュール（tool_progress 等）には依存しない。"""

import threading

from sqlalchemy.orm import Session

from ..models import AgentRun
from . import trace

_wake = threading.Event()


def request_planning(db: Session, case_id: str, input_text: str | None = None) -> AgentRun | None:
    """依頼の計画（AG-001 → AG-002 → AG-003）を待ちに入れる。すでに待ち・実行中なら None。"""
    run = trace.enqueue_run(db, "plan", case_id=case_id, input_text=input_text)
    if run is not None:
        _wake.set()
    return run


def request_dispute(db: Session, dispute_id: str, input_text: str | None = None) -> AgentRun | None:
    """紛争の論点整理（AG-001 → AG-004）を待ちに入れる。すでに待ち・実行中なら None。"""
    run = trace.enqueue_run(db, "analyze_dispute", dispute_id=dispute_id, input_text=input_text)
    if run is not None:
        _wake.set()
    return run


def wait(timeout: float) -> None:
    """次の要求が来るか timeout 秒が経つまで待つ（ランナーのスレッド用）。"""
    _wake.wait(timeout=timeout)
    _wake.clear()
