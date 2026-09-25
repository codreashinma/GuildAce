from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import HumanTask, User
from ..schemas import HumanTaskAcceptIn, HumanTaskOut, HumanTaskSubmitIn
from ..services import gemini
from .cases import _load, check_delivered
from .world import verify_and_record

router = APIRouter(prefix="/human-tasks", tags=["human-tasks"])


@router.get("", response_model=list[HumanTaskOut])
def list_open(db: Session = Depends(get_db)):
    return db.query(HumanTask).filter(HumanTask.status == "open").order_by(HumanTask.created_at.desc()).all()


@router.get("/mine", response_model=list[HumanTaskOut])
def list_mine(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(HumanTask).filter(HumanTask.worker_id == user.id).order_by(HumanTask.created_at.desc()).all()


@router.get("/{task_id}", response_model=HumanTaskOut)
def get_task(task_id: str, db: Session = Depends(get_db)):
    ht = db.get(HumanTask, task_id)
    if ht is None:
        raise HTTPException(404)
    return ht


@router.post("/{task_id}/accept", response_model=HumanTaskOut)
def accept(task_id: str, body: HumanTaskAcceptIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ht = db.get(HumanTask, task_id)
    if ht is None:
        raise HTTPException(404)
    if ht.status != "open":
        raise HTTPException(400, "このタスクは受注できません")
    if ht.case.client_id == user.id:
        raise HTTPException(403, "発注者は自分の案件の Human Task を受注できません")
    verify_and_record(db, user, action="human-task", signal=ht.id, idkit_response=body.idkit_response)
    ht.worker_id, ht.status = user.id, "accepted"
    db.commit()
    db.refresh(ht)
    return ht


@router.post("/{task_id}/cancel", response_model=HumanTaskOut)
def cancel(task_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ht = db.get(HumanTask, task_id)
    if ht is None or ht.worker_id != user.id or ht.status != "accepted":
        raise HTTPException(400, "キャンセルできません")
    ht.worker_id, ht.status = None, "open"
    db.commit()
    db.refresh(ht)
    return ht


@router.post("/{task_id}/submit", response_model=HumanTaskOut)
def submit(task_id: str, body: HumanTaskSubmitIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ht = db.get(HumanTask, task_id)
    if ht is None or ht.worker_id != user.id or ht.status != "accepted":
        raise HTTPException(400, "提出できません")
    ht.submission, ht.status = body.submission, "submitted"
    db.commit()
    check = gemini.check_human_submission(task_title=ht.title, task_description=ht.description, submission=body.submission)
    ht.ai_check = check.comment
    ht.status = "done"
    task = ht.task
    task.deliverable = f"{body.submission}\n\n---\nPM Agent の確認: {check.comment}"
    task.status, task.completed_at = "done", datetime.now(UTC)
    db.commit()
    check_delivered(db, _load(db, ht.case_id))
    db.refresh(ht)
    return ht
