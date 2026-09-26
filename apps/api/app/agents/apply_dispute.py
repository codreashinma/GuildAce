"""紛争の論点を disputes.summary_json に写し、Jury の画面（HIL-004）へつなぐ（WP-019 / AG-004 の出力・HIL-004）。
AG-001 の紛争モードの実行が終わったあと、ランナーが呼ぶ。決定的なコードで、LLM は呼ばない。
- 写すのは、同じ AG-001 の実行が TOOL-007 で保存した論点（agent-definitions AG-004 の「出力」の issues をそのまま）
- 形: {"source": "agents", "version": 版, "issues": [...], "no_issues": bool, "no_issues_reason": 理由の種類, "ref_labels": {参照: 表示名}}
- 論点なし（AG-004 の失敗・上限・停止）でもその旨を入れる。裁定は人間が行えるので、投票は止めない
- ref_labels は evidence_refs（deliverable:<タスク ID> / approval:<承認 ID>）を、DB のタスク名で表示するための対応表
- summary_json の既存のキー（投票で入る resolve_jobs）は残す"""

import re

from sqlalchemy.orm import Session

from ..models import AgentOutput, AgentRun, Approval, Dispute, Task

_REASON = re.compile(r"^[a-z_]{1,30}$")  # 理由は種類の名前だけを残す（自由文やモデルの出力を画面に出さない）


def ref_labels(db: Session, case_id: str) -> dict[str, str]:
    """紛争の案件の記録の参照（TOOL-003 と同じ ID）→ 画面に出す名前"""
    out: dict[str, str] = {}
    for t in db.query(Task).filter(Task.case_id == case_id).order_by(Task.order_no):
        out[f"deliverable:{t.id}"] = f"成果物: {t.title}"
        for a in db.query(Approval).filter(Approval.task_id == t.id).order_by(Approval.created_at):
            out[f"approval:{a.id}"] = f"承認: {t.title}"
    return out


def _saved_of_run(db: Session, run: AgentRun) -> AgentOutput | None:
    return (db.query(AgentOutput).filter_by(kind="dispute_summary", target_id=run.dispute_id, run_id=run.id)
            .order_by(AgentOutput.revision.desc()).first())


def apply(db: Session, run: AgentRun, no_issues_reason: str | None = None) -> dict | None:
    """この実行の論点（無ければ論点なし）を summary_json に写して返す。紛争が無ければ None。"""
    # 投票（別のセッション）が書いた resolve_jobs を消さないよう、DB から読み直してから足す
    d = db.get(Dispute, run.dispute_id, populate_existing=True)
    if d is None:
        return None
    saved = _saved_of_run(db, run)
    issues = saved.payload["issues"] if saved else []
    reason = no_issues_reason or "empty"
    summary = {
        "source": "agents",
        "version": saved.revision if saved else None,
        "issues": issues,
        "no_issues": not issues,
        "no_issues_reason": None if issues else (reason if _REASON.match(reason) else "error"),
        "ref_labels": ref_labels(db, d.case_id),
    }
    d.summary_json = {**(d.summary_json or {}), **summary}
    db.commit()
    return d.summary_json
