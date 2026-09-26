from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..db import get_db
from ..models import HumanTask, User
from ..schemas import HumanTaskAcceptIn, HumanTaskOut, HumanTaskSubmitIn
from ..services import assign, gemini
from .cases import submit_human_task
from .world import verify_and_record

router = APIRouter(prefix="/human-tasks", tags=["human-tasks"])


@router.get("", response_model=list[HumanTaskOut])
def list_open(db: Session = Depends(get_db)):
    return db.query(HumanTask).filter(HumanTask.status == "open").order_by(HumanTask.created_at.desc()).all()


@router.get("/assigned", response_model=list[HumanTaskOut])
def list_assigned(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """自分（のウォレットに紐づく人員）に指名されたタスク"""
    from ..models import Member

    member_ids = [m.id for m in db.query(Member).filter(Member.wallet_address == user.wallet_address)]
    if not member_ids:
        return []
    return db.query(HumanTask).filter(HumanTask.status == "assigned", HumanTask.assignee_member_id.in_(member_ids)).order_by(HumanTask.created_at.desc()).all()


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
    if ht.status not in ("open", "assigned"):
        raise HTTPException(400, "このタスクは受注できません")
    if ht.case.client_id == user.id:
        raise HTTPException(403, "発注者は自分の案件の Human Task を受注できません")
    if ht.status == "assigned" and (ht.assignee is None or ht.assignee.wallet_address != user.wallet_address):
        raise HTTPException(403, "このタスクは別の人員に指名されています")
    verify_and_record(db, user, action="human-task", signal=ht.id, idkit_response=body.idkit_response)
    ht.worker_id, ht.status = user.id, "accepted"
    db.commit()
    db.refresh(ht)
    return ht


@router.post("/{task_id}/decline", response_model=HumanTaskOut)
def decline(task_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """指名された本人が辞退 → PM Agent が次の候補に再指名"""
    ht = db.get(HumanTask, task_id)
    if ht is None or ht.status != "assigned" or ht.assignee is None or ht.assignee.wallet_address != user.wallet_address:
        raise HTTPException(400, "辞退できません")
    ht.declined_member_ids = [*(ht.declined_member_ids or []), ht.assignee_member_id]
    db.commit()
    assign.assign(db, ht)
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
    submit_human_task(db, ht)
    db.refresh(ht)
    return ht
