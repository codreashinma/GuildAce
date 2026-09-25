from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..models import Company, Member, User
from ..schemas import CompanyCreateIn, CompanyOut, MemberCreateIn, MemberOut, MemberUpdateIn, TxIn
from ..services import ens

router = APIRouter(prefix="/companies", tags=["companies"])


def _company(db: Session, company_id: str, user: User | None = None) -> Company:
    c = db.get(Company, company_id)
    if c is None:
        raise HTTPException(404, "会社が見つかりません")
    if user is not None and c.admin_id != user.id:
        raise HTTPException(403, "会社の管理者のみ操作できます")
    return c


def member_texts(m: Member) -> dict[str, str]:
    return {
        "codrea.person.company": m.company.ens_name, "codrea.person.name": m.name, "codrea.person.role": m.role, "codrea.person.skills": m.skills,
        "codrea.person.location": m.location, "codrea.person.available": "true" if m.available else "false",
    }


@router.get("", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return db.query(Company).order_by(Company.created_at.desc()).all()


@router.get("/mine", response_model=list[CompanyOut])
def my_companies(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.query(Company).filter(Company.admin_id == user.id).all()


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if db.query(Company).filter(Company.ens_name == body.ens_name).first():
        raise HTTPException(409, "この ENS 名は登録済みです")
    owner = ens.name_owner(body.ens_name)
    verified = owner is not None and owner.lower() == user.wallet_address
    if owner is not None and not verified:
        raise HTTPException(403, f"{body.ens_name} の所有者（{owner}）が接続中のウォレットと一致しません")
    c = Company(admin_id=user.id, name=body.name, ens_name=body.ens_name, description=body.description, ens_verified=verified)
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


@router.get("/{company_id}", response_model=CompanyOut)
def get_company(company_id: str, db: Session = Depends(get_db)):
    return _company(db, company_id)


@router.post("/{company_id}/members", response_model=MemberOut, status_code=201)
def add_member(company_id: str, body: MemberCreateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _company(db, company_id, user)
    if any(m.label == body.label for m in c.members):
        raise HTTPException(409, "このラベルは既に使われています")
    m = Member(company_id=c.id, label=body.label, name=body.name, wallet_address=body.wallet_address.lower(), ens_name=f"{body.label}.{c.ens_name}",
               role=body.role, skills=body.skills, location=body.location, available=body.available)
    db.add(m)
    db.commit()
    db.refresh(m)
    return m


@router.patch("/{company_id}/members/{member_id}", response_model=MemberOut)
def update_member(company_id: str, member_id: str, body: MemberUpdateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _company(db, company_id, user)
    m = db.get(Member, member_id)
    if m is None or m.company_id != company_id:
        raise HTTPException(404)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(m, k, v)
    if m.ens_status == "written":
        m.ens_status = "pending"  # record が変わったので再書き込みが必要
    db.commit()
    db.refresh(m)
    return m


@router.get("/{company_id}/members/{member_id}/ens-calldata")
def member_ens_calldata(company_id: str, member_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    c = _company(db, company_id, user)
    m = db.get(Member, member_id)
    if m is None or m.company_id != company_id:
        raise HTTPException(404)
    if not get_settings().sepolia_rpc_url:
        return {"mock": True, "txs": [], "note": "RPC 未設定のため ENS 書き込みはモックです"}
    try:
        txs = ens.member_calldata(company_name=c.ens_name, label=m.label, owner=m.wallet_address, texts=member_texts(m))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e
    return {"mock": False, "txs": txs}


@router.post("/{company_id}/members/{member_id}/ens-written", response_model=MemberOut)
def member_ens_written(company_id: str, member_id: str, body: TxIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    _company(db, company_id, user)
    m = db.get(Member, member_id)
    if m is None or m.company_id != company_id:
        raise HTTPException(404)
    m.ens_status, m.ens_tx_hash = "written", body.tx_hash
    db.commit()
    db.refresh(m)
    return m
