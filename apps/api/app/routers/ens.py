"""ENS 専用 API（ENSv2 / Sepolia の読み取りと、利用者が自分のウォレットで署名するための準備）。
すべて DB を介さずオンチェーンの値を返す。RPC 未設定（モック）のときは configured=False を返す。"""

import time

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from web3 import Web3

from ..auth import current_user
from ..config import get_settings
from ..db import get_db
from ..models import Agent, Case, Company, Member
from ..services import ens

ENSIP10_ABI = [
    {"type": "function", "name": "resolve", "stateMutability": "view", "inputs": [{"name": "name", "type": "bytes"}, {"name": "data", "type": "bytes"}], "outputs": [{"type": "bytes"}]},
    {"type": "function", "name": "supportsInterface", "stateMutability": "view", "inputs": [{"name": "interfaceId", "type": "bytes4"}], "outputs": [{"type": "bool"}]},
]
IEXTENDED_RESOLVER = bytes.fromhex("9061b923")  # ENSIP-10 IExtendedResolver

router = APIRouter(prefix="/ens", tags=["ens"])

ALL_TEXT_KEYS = list(dict.fromkeys([*ens.PROFILE_KEYS, *ens.SUBAGENT_KEYS, *ens.PROJECT_KEYS, *ens.PERSON_KEYS]))
_cache: dict[str, tuple[float, dict]] = {}


def _valid_name(name: str) -> str:
    n = name.strip().lower()
    labels = n.split(".")
    if len(labels) < 2 or labels[-1] != "eth" or any(not l or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in l) for l in labels):
        raise HTTPException(400, "Specify the name as <label>.eth (lowercase letters, digits, hyphens)")
    return n


def resolve_name(name: str, ttl: float = 60.0) -> dict:
    """レジストリを .eth から順にたどり、所有者・レジストリ・リゾルバ・addr・text record を返す（60 秒キャッシュ）。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return {"name": name, "configured": False, "registered": False, "source": "mock"}
    hit = _cache.get(name)
    if hit and time.time() - hit[0] < ttl:
        return dict(hit[1])
    w3 = ens._w3()
    out: dict = {"name": name, "configured": True, "registered": False, "source": "registry-walk",
                 "owner": None, "registry": None, "subregistry": None, "resolver": None, "addr": None, "texts": {}, "expiry": None}
    try:
        resolver_addr, parent_registry, label = ens.resolve_v2(w3, name)
        if parent_registry is None:
            _cache[name] = (time.time(), dict(out))
            return out
        reg = w3.eth.contract(address=parent_registry, abi=ens.V2_REGISTRY_ABI)
        status, expiry, owner, _, _ = reg.functions.getState(ens._labelhash_int(label)).call()
        sub = reg.functions.getSubregistry(label).call()
        out.update({
            "registered": status == 2, "owner": owner if int(owner, 16) else None, "registry": parent_registry,
            "subregistry": sub if int(sub, 16) else None, "resolver": resolver_addr, "expiry": int(expiry) or None,
        })
        if resolver_addr:
            out["addr"], texts = _read_records(w3, resolver_addr, name)
            out["texts"] = texts
            out["wildcard"] = _ensip10_check(w3, resolver_addr, name, texts)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Failed to read from Sepolia: {type(e).__name__}") from e
    _cache[name] = (time.time(), dict(out))
    return out


def _read_records(w3, resolver_addr: str, name: str) -> tuple[str | None, dict[str, str]]:
    """addr と全 text key を Multicall3 の 1 回の eth_call で読む。失敗時は 1 件ずつ読む。"""
    r = w3.eth.contract(address=resolver_addr, abi=ens.RESOLVER_ABI)
    node = ens.namehash(name)
    try:
        calls = [(resolver_addr, r.encode_abi("addr", args=[node]))] + [(resolver_addr, r.encode_abi("text", args=[node, k])) for k in ALL_TEXT_KEYS]
        results = ens.multicall(w3, calls)
        addr = None
        ok, raw = results[0]
        if ok and len(raw) >= 32:
            (a,) = w3.codec.decode(["address"], raw)
            addr = Web3.to_checksum_address(a) if int(a, 16) else None
        texts = {k: v for k, (ok, raw) in zip(ALL_TEXT_KEYS, results[1:], strict=True) if (v := ens.decode_text(w3, ok, raw))}
        return addr, texts
    except Exception:  # noqa: BLE001
        pass
    try:
        a = r.functions.addr(node).call()
        addr = a if int(a, 16) else None
    except Exception:  # noqa: BLE001
        addr = None
    texts = {}
    for k in ALL_TEXT_KEYS:
        try:
            v = r.functions.text(node, k).call()
        except Exception:  # noqa: BLE001
            continue
        if v:
            texts[k] = v
    return addr, texts


def _ensip10_check(w3, resolver_addr: str, name: str, texts: dict[str, str]) -> dict:
    """ENSIP-10（ワイルドカード解決）経路の確認。
    レジストリを辿って見つけたリゾルバに DNS エンコードした名前と text() の calldata を渡し、
    `resolve(bytes,bytes)` が直読みと同じ値を返すかを示す。Sepolia の UniversalResolver は現時点で v2 名を見つけられないため、
    ここでは「リゾルバが ENSIP-10 に応答する」ことを実値で示す。"""
    r = w3.eth.contract(address=resolver_addr, abi=ENSIP10_ABI)
    out: dict = {"supported": False, "checked_key": None, "value": None, "matches": None}
    try:
        out["supported"] = bool(r.functions.supportsInterface(IEXTENDED_RESOLVER).call())
    except Exception:  # noqa: BLE001
        return out
    if not out["supported"] or not texts:
        return out
    key = next(iter(texts))
    plain = w3.eth.contract(abi=ens.RESOLVER_ABI).encode_abi("text", args=[ens.namehash(name), key])
    try:
        raw = r.functions.resolve(ens.dns_encode(name), bytes.fromhex(plain[2:])).call()
        (val,) = w3.codec.decode(["string"], raw)
        out.update({"checked_key": key, "value": val, "matches": val == texts[key]})
    except Exception as e:  # noqa: BLE001
        out["error"] = type(e).__name__
    return out


@router.get("/resolve")
def resolve(name: str = Query(min_length=5, max_length=255)):
    """任意の ENS 名（ENSv2 / Sepolia）の所有者・レジストリ・リゾルバ・addr・text record を返す。
    Agent / project subname / 人員の record 表示に使う（scripts/ens_check.py の API 化）。"""
    return resolve_name(_valid_name(name))


@router.get("/keys")
def keys():
    """このプラットフォームが使う text record キーの一覧（表示用）"""
    return {"profile": ens.PROFILE_KEYS, "reputation": ens.REPUTATION_KEYS, "subagent": ens.SUBAGENT_KEYS, "project": ens.PROJECT_KEYS, "person": ens.PERSON_KEYS}



def readiness_of(name: str) -> dict:
    """名前に subname を発行できる状態か（登録済み・サブレジストリ・リゾルバの 3 点）。無いと register が revert する。"""
    r = resolve_name(name)
    if not r["configured"]:
        return {"name": name, "configured": False, "ready": False, "registered": False, "subregistry": None, "resolver": None, "missing": [], "note": "RPC not configured (mock)"}
    missing = []
    if not r["registered"]:
        missing.append("registered")
    if not r["subregistry"]:
        missing.append("subregistry")
    if not r["resolver"]:
        missing.append("resolver")
    steps = {
        "registered": f"Register {name} on ENSv2 (Sepolia)",
        "subregistry": "The name Owner deploys a UserRegistry (Subregistry) and calls setSubregistry",
        "resolver": "The name Owner deploys an OwnedResolver and calls setResolver",
    }
    return {"name": name, "configured": True, "ready": not missing, "registered": r["registered"], "owner": r["owner"],
            "subregistry": r["subregistry"], "resolver": r["resolver"], "missing": missing, "next_steps": [steps[m] for m in missing]}


@router.get("/readiness")
def readiness(name: str = Query(min_length=5, max_length=255)):
    """Creator 所有の Agent（D1）や会社の人員（E1）を発行する前提が揃っているかを返す。"""
    return readiness_of(_valid_name(name))


@router.get("/check-owner")
def check_owner(name: str = Query(min_length=5, max_length=255), user=Depends(current_user)):
    """入力中の名前が接続ウォレットの所有か（ENSv2 の latestOwner）。登録時の 403 を入力中に分かるようにする。"""
    n = _valid_name(name)
    r = resolve_name(n)
    if not r["configured"]:
        return {"name": n, "configured": False, "status": "unconfigured", "owner": None, "is_mine": None}
    if not r["registered"]:
        return {"name": n, "configured": True, "status": "unregistered", "owner": None, "is_mine": False}
    owner = r["owner"]
    return {"name": n, "configured": True, "status": "ok", "owner": owner, "is_mine": bool(owner and owner.lower() == user.wallet_address.lower()),
            "wallet": user.wallet_address}


@router.get("/setup-calldata")
def setup_calldata(name: str = Query(min_length=5, max_length=255), user=Depends(current_user)):
    """名前の所有者が自分のウォレットで署名する、OwnedResolver デプロイ・UserRegistry デプロイ・setResolver・setSubregistry の calldata。
    Creator（D1）と会社（E1）が運用者に頼らず subname を発行できる状態を自分で作る（Permissioned Resolver: データの所有者は名前の所有者）。"""
    n = _valid_name(name)
    if not get_settings().sepolia_rpc_url:
        return {"name": n, "mock": True, "txs": [], "ready": True, "note": "RPC not configured (mock)"}
    try:
        out = ens.setup_calldata(name=n, owner=user.wallet_address)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Failed to read from Sepolia: {type(e).__name__}") from e
    _cache.pop(n, None)
    ens.invalidate_walk(n)
    return {"mock": False, **out}


# ---------------------------------------------------------------- 逆引きと発行名の一覧（監査・表示用）


def _reverse_one(db: Session, address: str) -> dict:
    a = address.lower()
    m = db.query(Member).filter(Member.wallet_address == a).order_by(Member.created_at).first()
    if m is not None:
        return {"address": a, "name": m.ens_name, "source": "member", "verified": m.ens_status == "written"}
    ag = db.query(Agent).filter(Agent.payout_address == a, Agent.status == "published", Agent.ens_name.isnot(None)).order_by(Agent.created_at).first()
    if ag is not None:
        return {"address": a, "name": ag.ens_name, "source": "agent", "verified": bool(ag.ens_tx_hash and not ag.ens_tx_hash.startswith("0xmock"))}
    from ..models import User

    u = db.query(User).filter(User.wallet_address == a).first()
    if u is not None:
        c = db.query(Company).filter(Company.admin_id == u.id).order_by(Company.created_at).first()
        if c is not None:
            return {"address": a, "name": c.ens_name, "source": "company-admin", "verified": c.ens_verified}
    return {"address": a, "name": None, "source": None, "verified": False}


@router.get("/reverse")
def reverse(address: list[str] = Query(min_length=1, max_length=50), db: Session = Depends(get_db)):
    """アドレス → ENS 名。ENSv2（Sepolia beta）にはまだ逆引きが無いため、このプラットフォームが発行した名前
    （人員 / Agent の受取アドレス / 会社管理者）から引く。承認者・Jury・レビュー投稿者を名前で表示するのに使う。"""
    out = {}
    for addr in address:
        if not Web3.is_address(addr):
            raise HTTPException(400, f"Invalid address format: {addr}")
        out[addr.lower()] = _reverse_one(db, addr)
    return out


@router.get("/names")
def names(db: Session = Depends(get_db)):
    """プラットフォームが ENSv2（Sepolia）に発行した全名前（Agent・専門 subagent・reputation・案件 project・人員）と tx。
    ENS 賞のデモと監査向け。mock 発行（0xmock…）は kind に mock=True を付ける。"""
    s = get_settings()
    rows: list[dict] = []
    agents = db.query(Agent).filter(Agent.status == "published", Agent.ens_name.isnot(None)).order_by(Agent.created_at).all()
    for a in agents:
        mock = not a.ens_tx_hash or a.ens_tx_hash.startswith("0xmock")
        rows.append({"name": a.ens_name, "kind": "agent", "owner_mode": a.owner_mode, "tx_hash": a.ens_tx_hash, "created_at": a.created_at, "mock": mock,
                     "link": f"/agents/{a.id}", "subregistry": a.ens_subregistry, "note": "Issued by the Creator's Wallet (Namespace root = Creator)" if a.owner_mode == "creator" else None})
        if not mock and (a.owner_mode == "platform" or a.ens_subregistry):
            rows.append({"name": ens.reputation_name_of(a.ens_name), "kind": "reputation", "owner_mode": a.owner_mode, "tx_hash": a.ens_tx_hash, "created_at": a.created_at, "mock": False, "link": f"/agents/{a.id}", "note": "Owned and updated by the Reputation key"})
            for sub in (a.subagents if a.subagents is not None else ens.DEFAULT_SUBAGENTS):
                rows.append({"name": f"{sub['role']}.{a.ens_name}", "kind": "subagent", "owner_mode": a.owner_mode, "tx_hash": a.ens_tx_hash, "created_at": a.created_at, "mock": False, "link": f"/agents/{a.id}", "note": sub.get("name")})
    for c in db.query(Case).filter(Case.project_ens_name.isnot(None)).order_by(Case.created_at).all():
        rows.append({"name": c.project_ens_name, "kind": "project", "owner_mode": "platform", "tx_hash": c.project_ens_tx_hash, "created_at": c.created_at,
                     "mock": not c.project_ens_tx_hash or c.project_ens_tx_hash.startswith("0xmock"), "link": f"/cases/{c.id}", "note": "Issued and updated by the Project key"})
    for m in db.query(Member).filter(Member.ens_status == "written").order_by(Member.created_at).all():
        rows.append({"name": m.ens_name, "kind": "person", "owner_mode": "company", "tx_hash": m.ens_tx_hash, "created_at": m.created_at,
                     "mock": not m.ens_tx_hash or m.ens_tx_hash.startswith("0xmock"), "link": "/companies", "note": "Issued by the Company admin's Wallet"})
    return {"parent": s.ens_parent_name, "count": len(rows), "names": rows}


@router.get("/register-calldata")
def register_calldata(name: str = Query(min_length=5, max_length=255), phase: str = Query(pattern="^(commit|register)$"), secret: str | None = None, user=Depends(current_user)):
    """利用者が自分のウォレットで .eth（2LD）を登録する calldata（commit → 60 秒 → register）。
    登録後は /ens/setup-calldata でリゾルバとサブレジストリを用意すると、Agent や人員の subname を発行できる。"""
    n = _valid_name(name)
    if not get_settings().sepolia_rpc_url:
        return {"name": n, "mock": True, "txs": [], "note": "RPC not configured (mock)"}
    try:
        out = ens.register_calldata(name=n, owner=user.wallet_address, phase=phase, secret=secret)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(502, f"Failed to read from Sepolia: {type(e).__name__}") from e
    _cache.pop(n, None)
    ens.invalidate_walk(n)
    return {"mock": False, **out}
