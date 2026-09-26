"""ENSv2（Sepolia beta）連携。
- 公開: 親名 choice.eth のサブレジストリに subname を register し、OwnedResolver に text record を書く
- 更新: 評価・完了数などの text record を更新
- 読み取り: UniversalResolver 経由で text record を読む
ENS_WRITE_ENABLED=false のときはモック（tx hash を生成せず ens_name だけ確定）。

役割ビットマップ等は ensdomains/ens-cli の v2.ts に合わせている。"""

import logging
import secrets
import time

from eth_utils import keccak
from web3 import Web3
from web3.exceptions import ContractLogicError

from ..config import get_settings

# ENSv2 EAC の役割（ens-cli v2.ts より）
ROLE_UNREGISTER = 1 << 12
ROLE_RENEW = 1 << 16
ROLE_SET_SUBREGISTRY = 1 << 20
ROLE_SET_RESOLVER = 1 << 24
V2_DEFAULT_OWNER_ROLE_BITMAP = (
    ROLE_UNREGISTER | ROLE_RENEW | ROLE_SET_SUBREGISTRY | ROLE_SET_RESOLVER
    | (ROLE_UNREGISTER << 128) | (ROLE_RENEW << 128) | (ROLE_SET_SUBREGISTRY << 128) | (ROLE_SET_RESOLVER << 128)
)
ALL_ROLES = int("0x1111111111111111111111111111111111111111111111111111111111111111", 16)
ONE_YEAR = 365 * 24 * 3600

V2_REGISTRY_ABI = [
    {"type": "function", "name": "getSubregistry", "stateMutability": "view", "inputs": [{"name": "label", "type": "string"}], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "getResolver", "stateMutability": "view", "inputs": [{"name": "label", "type": "string"}], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "register", "stateMutability": "nonpayable", "inputs": [
        {"name": "label", "type": "string"}, {"name": "owner", "type": "address"}, {"name": "registry", "type": "address"},
        {"name": "resolver", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "expires", "type": "uint64"}],
     "outputs": [{"name": "tokenId", "type": "uint256"}]},
    {"type": "function", "name": "getState", "stateMutability": "view", "inputs": [{"name": "anyId", "type": "uint256"}],
     "outputs": [{"type": "tuple", "components": [{"name": "status", "type": "uint8"}, {"name": "expiry", "type": "uint64"}, {"name": "latestOwner", "type": "address"}, {"name": "tokenId", "type": "uint256"}, {"name": "resource", "type": "uint256"}]}]},
    {"type": "function", "name": "setSubregistry", "stateMutability": "nonpayable", "inputs": [{"name": "tokenId", "type": "uint256"}, {"name": "registry", "type": "address"}], "outputs": []},
    {"type": "function", "name": "setResolver", "stateMutability": "nonpayable", "inputs": [{"name": "anyId", "type": "uint256"}, {"name": "resolver", "type": "address"}], "outputs": []},
]
RESOLVER_ABI = [
    {"type": "function", "name": "setAddr", "stateMutability": "nonpayable", "inputs": [{"name": "node", "type": "bytes32"}, {"name": "addr", "type": "address"}], "outputs": []},
    {"type": "function", "name": "setText", "stateMutability": "nonpayable", "inputs": [{"name": "node", "type": "bytes32"}, {"name": "key", "type": "string"}, {"name": "value", "type": "string"}], "outputs": []},
    {"type": "function", "name": "text", "stateMutability": "view", "inputs": [{"name": "node", "type": "bytes32"}, {"name": "key", "type": "string"}], "outputs": [{"type": "string"}]},
    {"type": "function", "name": "addr", "stateMutability": "view", "inputs": [{"name": "node", "type": "bytes32"}], "outputs": [{"type": "address"}]},
    {"type": "function", "name": "multicall", "stateMutability": "nonpayable", "inputs": [{"name": "data", "type": "bytes[]"}], "outputs": [{"name": "results", "type": "bytes[]"}]},
]
UNIVERSAL_RESOLVER_ABI = [
    {"type": "function", "name": "findResolver", "stateMutability": "view", "inputs": [{"name": "name", "type": "bytes"}],
     "outputs": [{"type": "tuple", "components": [{"name": "resolver", "type": "address"}, {"name": "node", "type": "bytes32"}, {"name": "offset", "type": "uint256"}]}]},
]

# text record のキー（ENSIP の慣習に沿い、独自キーは codrea. 名前空間）
REPUTATION_KEYS = ["codrea.agent.rating", "codrea.agent.reviews", "codrea.agent.completed"]
PROJECT_KEYS = ["codrea.project.title", "codrea.project.case", "codrea.project.escrow", "codrea.project.escrow_case_id", "codrea.project.client", "codrea.project.status", "codrea.project.url"]
PROFILE_KEYS = ["description", "avatar", "url", "codrea.agent.category", "codrea.agent.fee_bps", "codrea.agent.creator", "codrea.agent.endpoint", *REPUTATION_KEYS]
# PM Agent 配下の専門 AI エージェント（Agent 名前空間の subname）。既定の 4 つは初期値で、所有者が追加・削除・編集できる（agents.subagents）
DEFAULT_SUBAGENTS = [
    {"role": "designer", "name": "Designer Agent", "description": "画面構成・ワイヤーフレーム・デザイン方針", "rules": ""},
    {"role": "frontend", "name": "Frontend Agent", "description": "画面の実装方針とコンポーネント設計", "rules": ""},
    {"role": "backend", "name": "Backend Agent", "description": "API 設計とデータモデル", "rules": ""},
    {"role": "qa", "name": "QA Agent", "description": "受け入れテストの観点と結果", "rules": ""},
]
SUBAGENT_ROLES = [x["role"] for x in DEFAULT_SUBAGENTS]  # 互換用（既定の役割）
SUBAGENT_KEYS = ["description", "codrea.agent.name", "codrea.agent.role", "codrea.agent.parent", "codrea.agent.kind"]


def subagent_texts(sub: dict, parent_name: str) -> dict[str, str]:
    """専門エージェント 1 件の text record。プロンプト（rules）は ENS に書かない"""
    return {"description": (sub.get("description") or sub.get("name") or sub["role"])[:200], "codrea.agent.name": (sub.get("name") or sub["role"])[:60],
            "codrea.agent.role": sub["role"], "codrea.agent.parent": parent_name, "codrea.agent.kind": "ai"}
PERSON_KEYS = ["codrea.person.company", "codrea.person.name", "codrea.person.role", "codrea.person.skills", "codrea.person.location", "codrea.person.available"]

# EAC（EnhancedAccessControl）: PermissionedResolver / PermissionedRegistry 共通
RESOLVER_ROLE_SET_ADDR = 1 << 0
RESOLVER_ROLE_SET_TEXT = 1 << 4
REGISTRY_ROLE_REGISTRAR = 1 << 0
EAC_ABI = [
    {"type": "function", "name": "grantRoles", "stateMutability": "nonpayable", "inputs": [{"name": "resource", "type": "uint256"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "account", "type": "address"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "grantRootRoles", "stateMutability": "nonpayable", "inputs": [{"name": "roleBitmap", "type": "uint256"}, {"name": "account", "type": "address"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "roles", "stateMutability": "view", "inputs": [{"name": "resource", "type": "uint256"}, {"name": "account", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "hasRoles", "stateMutability": "view", "inputs": [{"name": "resource", "type": "uint256"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "account", "type": "address"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "hasRootRoles", "stateMutability": "view", "inputs": [{"name": "roleBitmap", "type": "uint256"}, {"name": "account", "type": "address"}], "outputs": [{"type": "bool"}]},
]


def eac_resource(node: bytes, key: str | None) -> int:
    """PermissionedResolver の resource ID = keccak(node, keccak(key))。node=0 なら「どの名前でもそのキー」。"""
    from eth_abi import encode

    part = keccak(text=key) if key else b"\x00" * 32
    if not any(node) and not key:
        return 0
    return int.from_bytes(keccak(encode(["bytes32", "bytes32"], [node, part])), "big")


def namehash(name: str) -> bytes:
    node = b"\x00" * 32
    if name:
        for label in reversed(name.split(".")):
            node = keccak(node + keccak(text=label))
    return node


def dns_encode(name: str) -> bytes:
    out = b""
    for label in name.split("."):
        b = label.encode()
        out += bytes([len(b)]) + b
    return out + b"\x00"


MULTICALL3 = "0xcA11bde05977b3631167028862bE2a173976CA11"  # Sepolia を含む主要チェーン共通のアドレス
MULTICALL3_ABI = [{"type": "function", "name": "aggregate3", "stateMutability": "payable",
                   "inputs": [{"name": "calls", "type": "tuple[]", "components": [{"name": "target", "type": "address"}, {"name": "allowFailure", "type": "bool"}, {"name": "callData", "type": "bytes"}]}],
                   "outputs": [{"name": "returnData", "type": "tuple[]", "components": [{"name": "success", "type": "bool"}, {"name": "returnData", "type": "bytes"}]}]}]


def multicall(w3: Web3, calls: list[tuple[str, str]]) -> list[tuple[bool, bytes]]:
    """複数の view 呼び出しを Multicall3 の aggregate3 で 1 回の eth_call にまとめる。calls = [(to, calldata hex)]。
    Render → RPC の往復（約 0.5 秒）が呼び出し数ぶん直列に積み上がるのを防ぐ。個々の失敗は (False, b"") で返る。"""
    if not calls:
        return []
    mc = w3.eth.contract(address=Web3.to_checksum_address(MULTICALL3), abi=MULTICALL3_ABI)
    res = mc.functions.aggregate3([(Web3.to_checksum_address(to), True, bytes.fromhex(data[2:])) for to, data in calls]).call()
    return [(bool(ok), bytes(raw)) for ok, raw in res]


def decode_text(w3: Web3, ok: bool, raw: bytes) -> str:
    if not ok or len(raw) < 64:
        return ""
    try:
        (v,) = w3.codec.decode(["string"], raw)
        return v
    except Exception:  # noqa: BLE001
        return ""


def decode_bool(ok: bool, raw: bytes) -> bool:
    return bool(ok and len(raw) >= 32 and int.from_bytes(raw[:32], "big"))


# レジストリ走査（.eth → サブレジストリ → リゾルバ）の結果。構造はほぼ変わらないので 5 分キャッシュ（見つかった場合のみ）。書き込み後は invalidate_walk で消す
_walk_cache: dict[str, tuple[float, tuple[str, str, str]]] = {}
WALK_TTL = 300.0


def invalidate_walk(name: str | None = None) -> None:
    if name is None:
        _walk_cache.clear()
        return
    n = name.lower()
    for k in [k for k in _walk_cache if k == n or k.endswith("." + n)]:
        _walk_cache.pop(k, None)


def resolve_v2(w3: Web3, name: str) -> tuple[str | None, str | None, str | None]:
    """ENSv2 のレジストリを .eth から順にたどり、(resolver, 親レジストリ, 最終ラベル) を返す。
    Universal Resolver が v2 名を解決しない期間があるため、レジストリを直接歩く。リゾルバが見つかった結果だけ 5 分キャッシュする。"""
    hit = _walk_cache.get(name.lower())
    if hit and time.time() - hit[0] < WALK_TTL:
        return hit[1]
    out = _resolve_v2_uncached(w3, name)
    if out[0]:
        _walk_cache[name.lower()] = (time.time(), out)  # type: ignore[assignment]
    return out


def _resolve_v2_uncached(w3: Web3, name: str) -> tuple[str | None, str | None, str | None]:
    s = get_settings()
    labels = name.split(".")
    if labels[-1] != "eth" or len(labels) < 2:
        return None, None, None
    registry = Web3.to_checksum_address(s.ensv2_eth_registry)
    for i in range(len(labels) - 2, -1, -1):
        label = labels[i]
        reg = w3.eth.contract(address=registry, abi=V2_REGISTRY_ABI)
        if i == 0:
            resolver = reg.functions.getResolver(label).call()
            return (resolver if int(resolver, 16) else None), registry, label
        sub = reg.functions.getSubregistry(label).call()
        if int(sub, 16) == 0:
            return None, None, None
        registry = Web3.to_checksum_address(sub)
    return None, None, None


def agent_ens_name(label: str) -> str:
    return f"{label}.{get_settings().ens_parent_name}"


def reputation_name_of(agent_name: str) -> str:
    return f"reputation.{agent_name}"


def subregistry_of(w3: Web3, name: str):
    """name の子（subname）を登録するレジストリ（name に設定されたサブレジストリ）。無ければ None。
    .eth レジストリから順に getSubregistry を辿る。"""
    s = get_settings()
    labels = name.lower().split(".")
    if labels[-1] != "eth" or len(labels) < 2:
        return None
    registry = Web3.to_checksum_address(s.ensv2_eth_registry)
    for label in reversed(labels[:-1]):
        reg = w3.eth.contract(address=registry, abi=V2_REGISTRY_ABI)
        sub = reg.functions.getSubregistry(label).call()
        if int(sub, 16) == 0:
            return None
        registry = Web3.to_checksum_address(sub)
    return w3.eth.contract(address=registry, abi=V2_REGISTRY_ABI)


def owner_of(w3: Web3, name: str) -> str | None:
    """name の所有者（親レジストリの getState.latestOwner）。未登録は None。"""
    labels = name.lower().split(".")
    if len(labels) < 2:
        return None
    parent = subregistry_of(w3, ".".join(labels[1:])) if len(labels) > 2 else w3.eth.contract(address=Web3.to_checksum_address(get_settings().ensv2_eth_registry), abi=V2_REGISTRY_ABI)
    if parent is None:
        return None
    status, _, owner, _, _ = parent.functions.getState(_labelhash_int(labels[0])).call()
    return owner if status == 2 else None


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(get_settings().sepolia_rpc_url))


_fallback_warned: set[str] = set()


def _account(role: str = "owner"):
    """署名鍵。owner = 運用ウォレット（名前の所有者）、reputation / project = EAC で限定された役割鍵。
    役割鍵が未設定なら owner にフォールバックする（役割分離なしの MVP 動作）。"""
    from eth_account import Account

    s = get_settings()
    key = {"owner": s.server_private_key, "reputation": s.reputation_private_key or s.server_private_key, "project": s.project_private_key or s.server_private_key}[role]
    if role != "owner" and not {"reputation": s.reputation_private_key, "project": s.project_private_key}[role] and role not in _fallback_warned:
        _fallback_warned.add(role)
        logging.getLogger(__name__).warning("ENS 役割鍵 %s が未設定のため Owner 鍵で署名します（EAC の役割分離なし）", role.upper())
    return Account.from_key(key)


def role_addresses() -> dict[str, str | None]:
    s = get_settings()
    return {r: (_account(r).address if s.server_private_key else None) for r in ("owner", "reputation", "project")}


def role_separation() -> dict:
    """運用鍵の役割分離の状態（/config で公開）。
    separated=False は Reputation / Project 鍵が未設定で Owner 鍵にフォールバックしている = EAC の分離がデモ上は効いていない。"""
    s = get_settings()
    addrs = role_addresses()
    separated = bool(s.server_private_key and s.reputation_private_key and s.project_private_key
                     and s.ens_reputation_resolver and s.ens_project_resolver
                     and len({(a or "").lower() for a in addrs.values()}) == 3)
    return {**addrs, "separated": separated,
            "reputation_resolver": s.ens_reputation_resolver or None, "project_resolver": s.ens_project_resolver or None}


def _send(w3: Web3, fn, role: str = "owner") -> str:
    s = get_settings()
    acct = _account(role)
    tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address), "chainId": s.chain_id})
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(h, timeout=240)
    if receipt["status"] != 1:
        raise RuntimeError(f"tx failed: {h.to_0x_hex()}")
    return h.to_0x_hex()


def _resolver(w3: Web3):
    s = get_settings()
    return w3.eth.contract(address=Web3.to_checksum_address(s.ens_owned_resolver), abi=RESOLVER_ABI)


def _role_resolver(w3: Web3, role: str):
    s = get_settings()
    addr = {"reputation": s.ens_reputation_resolver, "project": s.ens_project_resolver}[role]
    if not addr:
        raise RuntimeError(f"ENS_{role.upper()}_RESOLVER が未設定です（scripts/ens_role_resolvers.py）")
    return w3.eth.contract(address=Web3.to_checksum_address(addr), abi=RESOLVER_ABI)


def reputation_name(label: str) -> str:
    return f"reputation.{agent_ens_name(label)}"


def _subregistry(w3: Web3):
    s = get_settings()
    return w3.eth.contract(address=Web3.to_checksum_address(s.ens_parent_subregistry), abi=V2_REGISTRY_ABI)


def _records_calldata(w3: Web3, node: bytes, texts: dict[str, str], addr: str | None, r=None) -> list[bytes]:
    r = r or _resolver(w3)
    data: list[bytes] = []
    if addr:
        data.append(bytes.fromhex(r.encode_abi("setAddr", args=[node, Web3.to_checksum_address(addr)])[2:]))
    for k, v in texts.items():
        data.append(bytes.fromhex(r.encode_abi("setText", args=[node, k, v])[2:]))
    return data


def publish_agent(*, label: str, payout_address: str, texts: dict[str, str], subagents: list[dict] | None = None) -> tuple[str, str]:
    """subname を発行してプロフィールを書き、Agent 用のサブレジストリを用意する。(ens_name, tx_hash) を返す。"""
    s = get_settings()
    name = agent_ens_name(label)
    if not s.ens_write_enabled:
        return name, "0xmock" + secrets.token_hex(29)
    if not (s.ens_owned_resolver and s.ens_parent_subregistry and s.server_private_key):
        raise RuntimeError("ENS の設定が不足しています（ENS_OWNED_RESOLVER / ENS_PARENT_SUBREGISTRY / SERVER_PRIVATE_KEY）")
    w3 = _w3()
    acct = _account()
    reg = _subregistry(w3)
    expiry = int(time.time()) + ONE_YEAR
    existing = reg.functions.getResolver(label).call()
    if int(existing, 16) == 0:
        _send(w3, reg.functions.register(label, acct.address, "0x" + "00" * 20, Web3.to_checksum_address(s.ens_owned_resolver), V2_DEFAULT_OWNER_ROLE_BITMAP, expiry))
    node = namehash(name)
    main_texts = {k: v for k, v in texts.items() if k not in REPUTATION_KEYS} if s.ens_reputation_resolver else texts
    tx = _send(w3, _resolver(w3).functions.multicall(_records_calldata(w3, node, main_texts, payout_address)))
    # Agent を名前空間にする: 自身のサブレジストリを持ち、Project 鍵には「登録だけ」を許す（EAC ROLE_REGISTRAR、この Agent のサブレジストリに閉じる）
    sub = _ensure_subregistry(w3, reg, label, name)
    sub_reg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI)
    sub_eac = w3.eth.contract(address=sub, abi=EAC_ABI)
    project = _account("project").address
    if project.lower() != acct.address.lower() and not sub_eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, project).call():
        _send(w3, sub_eac.functions.grantRootRoles(REGISTRY_ROLE_REGISTRAR, project))
    # 専門 AI エージェントを Agent 名前空間の subname として発行（designer.<agent> など）。候補検索は ENS を参照する（FR-004）
    _sync_subagents_onchain(w3, acct, sub_reg, name, DEFAULT_SUBAGENTS if subagents is None else subagents, expiry)
    # Reputation は別 subname + 別リゾルバ（Reputation 鍵が admin）。所有者もリゾルバも Owner から分離される
    rep = _account("reputation").address
    if rep.lower() != acct.address.lower() and s.ens_reputation_resolver:
        if int(sub_reg.functions.getResolver("reputation").call(), 16) == 0:
            _send(w3, sub_reg.functions.register("reputation", rep, "0x" + "00" * 20, Web3.to_checksum_address(s.ens_reputation_resolver), V2_DEFAULT_OWNER_ROLE_BITMAP, expiry))
        rep_texts = {k: v for k, v in texts.items() if k in REPUTATION_KEYS}
        if rep_texts:
            rr = _role_resolver(w3, "reputation")
            _send(w3, rr.functions.multicall(_records_calldata(w3, namehash(reputation_name(label)), rep_texts, None, rr)), role="reputation")
    return name, tx


def _sync_subagents_onchain(w3: Web3, acct, sub_reg, name: str, subagents: list[dict], expiry: int) -> str | None:
    """（platform）専門エージェントの subname を無いものだけ発行し、record は全件書き直す（名前・説明の変更を反映）。削除分は触らない"""
    s = get_settings()
    calls: list[bytes] = []
    for sub in subagents:
        role = sub["role"]
        if int(sub_reg.functions.getResolver(role).call(), 16) == 0:
            _send(w3, sub_reg.functions.register(role, acct.address, "0x" + "00" * 20, Web3.to_checksum_address(s.ens_owned_resolver), V2_DEFAULT_OWNER_ROLE_BITMAP, expiry))
        calls += _records_calldata(w3, namehash(f"{role}.{name}"), subagent_texts(sub, name), None)
    if not calls:
        return None
    return _send(w3, _resolver(w3).functions.multicall(calls))


def sync_subagents(*, label: str, subagents: list[dict]) -> str:
    """（platform）公開後に専門エージェントを追加・編集したときの ENS 反映。ワーカーの ens_subagents ジョブから呼ぶ。モック時は疑似 tx"""
    s = get_settings()
    name = agent_ens_name(label)
    if not s.ens_write_enabled:
        return "0xmock" + secrets.token_hex(29)
    w3 = _w3()
    acct = _account()
    reg = _subregistry(w3)
    sub = _ensure_subregistry(w3, reg, label, name)
    sub_reg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI)
    tx = _sync_subagents_onchain(w3, acct, sub_reg, name, subagents, int(time.time()) + ONE_YEAR)
    return tx or "0xmock" + secrets.token_hex(29)


def subagents_calldata(*, name: str, owner: str, subagents: list[dict]) -> list[dict]:
    """（creator）専門エージェントの追加・編集を Creator のウォレットで反映する calldata。無い subname の register と、全件の record multicall"""
    w3 = _w3()
    owner = Web3.to_checksum_address(owner)
    label, parent_name = name.split(".", 1)
    sub_reg = subregistry_of(w3, name)
    if sub_reg is None:
        raise RuntimeError(f"{name} にサブレジストリがありません（Agent の公開時に作られます）")
    parent_resolver_addr, _, _ = resolve_v2(w3, parent_name)
    if parent_resolver_addr is None:
        raise RuntimeError(f"{parent_name} にリゾルバが設定されていません")
    pres = w3.eth.contract(address=parent_resolver_addr, abi=RESOLVER_ABI)
    expiry = int(time.time()) + ONE_YEAR
    zero = "0x" + "00" * 20
    txs: list[dict] = []
    calls: list[bytes] = []
    for sub in subagents:
        role = sub["role"]
        if int(sub_reg.functions.getResolver(role).call(), 16) == 0:
            txs.append({"to": sub_reg.address, "data": sub_reg.encode_abi("register", args=[role, owner, zero, parent_resolver_addr, V2_DEFAULT_OWNER_ROLE_BITMAP, expiry]), "label": f"{role}.{name} を発行（専門 AI エージェント）"})
        calls += _records_calldata(w3, namehash(f"{role}.{name}"), subagent_texts(sub, name), None, pres)
    if calls:
        txs.append({"to": parent_resolver_addr, "data": pres.encode_abi("multicall", args=[calls]), "label": "専門 AI エージェントの record を書き込み"})
    return txs


def _ensure_subregistry(w3: Web3, parent_registry, parent_label: str, parent_name: str) -> str:
    """親名（Agent）にサブレジストリが無ければデプロイして設定する。project subname の受け皿。"""
    s = get_settings()
    from eth_abi import encode

    sub = parent_registry.functions.getSubregistry(parent_label).call()
    if int(sub, 16):
        return sub
    acct = _account()
    factory = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_verifiable_factory), abi=[{"type": "function", "name": "deployProxy", "stateMutability": "nonpayable",
        "inputs": [{"name": "implementation", "type": "address"}, {"name": "salt", "type": "uint256"}, {"name": "data", "type": "bytes"}], "outputs": [{"type": "address"}]}])
    salt = int.from_bytes(keccak(encode(["bytes32", "bytes32", "uint256"], [keccak(text="UserRegistry"), namehash(parent_name), 0])), "big")
    init = w3.eth.contract(abi=[{"type": "function", "name": "initialize", "stateMutability": "nonpayable", "inputs": [{"name": "rootAccount", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}], "outputs": []}]).encode_abi("initialize", args=[acct.address, ALL_ROLES])
    fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:]))
    sub = fn.call({"from": acct.address})
    if w3.eth.get_code(sub) in (b"", b"\x00"):
        _send(w3, fn)
    _, _, _, token_id, _ = parent_registry.functions.getState(int.from_bytes(keccak(text=parent_label), "big")).call()
    _send(w3, parent_registry.functions.setSubregistry(token_id, sub))
    return sub


def publish_project(*, agent_label: str, project_label: str, texts: dict[str, str], agent_name: str | None = None) -> tuple[str, str]:
    """案件ごとの subname（project-<n>.<agent>）を発行し、record を書く（FR-027）。
    Project 鍵は Agent のサブレジストリで ROLE_REGISTRAR を持つ（platform は公開時に付与、creator は Creator が付与）。"""
    s = get_settings()
    agent = agent_name or agent_ens_name(agent_label)
    name = f"{project_label}.{agent}"
    if not s.ens_write_enabled:
        return name, "0xmock" + secrets.token_hex(29)
    w3 = _w3()
    project = _account("project")
    reg = subregistry_of(w3, agent)
    if reg is None:
        raise RuntimeError(f"{agent} にサブレジストリがありません（Agent の公開時に作られます）")
    # Project 鍵は ROLE_REGISTRAR しか持たないので、register と codrea.project.* の setText 以外は revert する
    pr = _role_resolver(w3, "project")
    if int(reg.functions.getResolver(project_label).call(), 16) == 0:
        _send(w3, reg.functions.register(project_label, project.address, "0x" + "00" * 20, pr.address, V2_DEFAULT_OWNER_ROLE_BITMAP, int(time.time()) + ONE_YEAR), role="project")
    node = namehash(name)
    texts = {k: v for k, v in texts.items() if k in PROJECT_KEYS}
    tx = _send(w3, pr.functions.multicall(_records_calldata(w3, node, texts, None, pr)), role="project")
    return name, tx


def update_texts(label: str, texts: dict[str, str], agent_name: str | None = None) -> str | None:
    """text record の更新。評価キーだけなら Reputation 鍵で reputation.<agent> に書く（EAC でそのキー以外は書けない）。
    agent_name を渡すと Creator 所有の Agent（<label>.<creator>.eth）。その場合プロフィールは Creator にしか書けないので評価キー以外は拒否する。"""
    s = get_settings()
    if not s.ens_write_enabled:
        return None
    w3 = _w3()
    name = agent_name or agent_ens_name(label)
    if texts and all(k in REPUTATION_KEYS for k in texts) and s.ens_reputation_resolver:
        rr = _role_resolver(w3, "reputation")
        return _send(w3, rr.functions.multicall(_records_calldata(w3, namehash(reputation_name_of(name)), texts, None, rr)), role="reputation")
    if agent_name:
        raise RuntimeError("Creator 所有の Agent のプロフィールはプラットフォームからは書けません（Creator が署名します）")
    node = namehash(name)
    return _send(w3, _resolver(w3).functions.multicall(_records_calldata(w3, node, texts, None)))


_read_cache: dict[tuple[str, tuple[str, ...]], tuple[float, dict[str, str]]] = {}


def read_texts(name: str, keys: list[str] | None = None, ttl: float = 60.0) -> dict[str, str]:
    """レジストリをたどって resolver を見つけ、text record を読む（60 秒キャッシュ）。失敗時は空 dict。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return {}
    ck = (name, tuple(keys or PROFILE_KEYS))
    hit = _read_cache.get(ck)
    if hit and time.time() - hit[0] < ttl:
        return dict(hit[1])
    try:
        w3 = _w3()
        resolver_addr, _, _ = resolve_v2(w3, name)
        if resolver_addr is None:
            return {}
        out = _texts_via_multicall(w3, [(resolver_addr, name, list(keys or PROFILE_KEYS))])[name]
        _read_cache[ck] = (time.time(), dict(out))
        return out
    except Exception:
        return {}


def _texts_via_multicall(w3: Web3, items: list[tuple[str, str, list[str]]]) -> dict[str, dict[str, str]]:
    """[(resolver, name, keys)] の text record を 1 回の eth_call で読む。"""
    r = w3.eth.contract(abi=RESOLVER_ABI)
    calls: list[tuple[str, str]] = []
    index: list[tuple[str, str]] = []
    for resolver_addr, name, keys in items:
        node = namehash(name)
        for k in keys:
            calls.append((resolver_addr, r.encode_abi("text", args=[node, k])))
            index.append((name, k))
    out: dict[str, dict[str, str]] = {name: {} for _, name, _ in items}
    for (name, k), (ok, raw) in zip(index, multicall(w3, calls), strict=True):
        v = decode_text(w3, ok, raw)
        if v:
            out[name][k] = v
    return out


def read_texts_many(items: list[tuple[str, list[str]]], ttl: float = 60.0) -> dict[str, dict[str, str]]:
    """複数の名前の text record をまとめて読む（Agent 詳細: 本体 + reputation + 専門 Agent 4 名を 1 回の eth_call で）。
    レジストリ走査はキャッシュ、リゾルバが無い名前は空 dict。"""
    s = get_settings()
    out: dict[str, dict[str, str]] = {name: {} for name, _ in items}
    if not s.sepolia_rpc_url:
        return out
    todo: list[tuple[str, str, list[str]]] = []
    try:
        w3 = _w3()
        for name, keys in items:
            ck = (name, tuple(keys))
            hit = _read_cache.get(ck)
            if hit and time.time() - hit[0] < ttl:
                out[name] = dict(hit[1])
                continue
            resolver_addr, _, _ = resolve_v2(w3, name)
            if resolver_addr:
                todo.append((resolver_addr, name, list(keys)))
        if todo:
            got = _texts_via_multicall(w3, todo)
            for _, name, keys in todo:
                out[name] = got[name]
                _read_cache[(name, tuple(keys))] = (time.time(), dict(got[name]))
    except Exception:  # noqa: BLE001
        logging.getLogger(__name__).exception("read_texts_many failed")
    return out


# ---------------------------------------------------------------- 会社所有の名前（会社管理者が署名する）

ETH_REGISTRY_ABI = V2_REGISTRY_ABI


def _labelhash_int(label: str) -> int:
    return int.from_bytes(keccak(text=label), "big")


def lookup_owner(name: str) -> tuple[str | None, str]:
    """ENSv2 の .eth 2LD の所有者を (owner, status) で返す。
    status: ok（登録済み）/ unregistered（未登録・期限切れ）/ error（RPC 失敗）/ unconfigured（RPC 未設定 = モック）。
    呼び出し側は unconfigured 以外で owner が None のときは「所有確認できない」として拒否する。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return None, "unconfigured"
    labels = name.lower().split(".")
    if len(labels) != 2 or labels[1] != "eth" or not labels[0]:
        return None, "unregistered"
    try:
        w3 = _w3()
        reg = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=ETH_REGISTRY_ABI)
        status, _, owner, _, _ = reg.functions.getState(_labelhash_int(labels[0])).call()
        return (owner, "ok") if status == 2 else (None, "unregistered")
    except Exception:
        return None, "error"


def name_owner(name: str) -> str | None:
    """後方互換: 所有者アドレス（確認できなければ None）"""
    return lookup_owner(name)[0]


def require_owner(name: str, wallet: str) -> bool:
    """名前の所有者が wallet であることを確認する。True = オンチェーンで確認済み、False = RPC 未設定で確認せず（モック）。
    確認できない・一致しないときは ValueError（メッセージは利用者向け）。"""
    owner, status = lookup_owner(name)
    if status == "unconfigured":
        return False
    if status == "error":
        raise ValueError(f"{name} の所有者を Sepolia から確認できませんでした（RPC エラー）。しばらくして再試行してください")
    if owner is None:
        raise ValueError(f"{name} は ENSv2（Sepolia）に登録されていません。先に登録してください")
    if owner.lower() != wallet.lower():
        raise ValueError(f"{name} の所有者（{owner}）が接続中のウォレットと一致しません")
    return True


def verify_written(*, name: str, tx_hash: str, sender: str, key: str) -> dict:
    """利用者のウォレットが送った ENS 書き込み tx の事後確認。
    レシートが成功していること、送信者が本人であること、名前の text record（key）が実際に読めることを確認する。
    RPC 未設定（モック）のときは確認せず {"mock": True} を返す。失敗は ValueError。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return {"mock": True}
    if tx_hash.startswith("0xmock"):
        raise ValueError("モックの tx hash はこの環境（RPC 設定済み）では受け付けません。ウォレットで実際に送信してください")
    w3 = _w3()
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
        tx = w3.eth.get_transaction(tx_hash)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"tx {tx_hash[:12]}… が見つかりません（未確定なら数秒後に再試行）: {type(e).__name__}") from e
    if receipt["status"] != 1:
        raise ValueError(f"tx {tx_hash[:12]}… は失敗（reverted）しています")
    if tx["from"].lower() != sender.lower():
        raise ValueError("tx の送信者が接続中のウォレットではありません")
    texts = read_texts(name, [key], ttl=0)
    if not texts.get(key):
        raise ValueError(f"{name} の text record（{key}）がまだ読めません。register と multicall の両方が確定しているか確認してください")
    return {"mock": False, "block": receipt["blockNumber"], "value": texts[key]}


def member_calldata(*, company_name: str, label: str, owner: str, texts: dict[str, str]) -> list[dict]:
    """名前の所有者（会社管理者・Creator）のウォレットで送る tx（register + record 書き込み）の calldata。
    親名のサブレジストリとリゾルバは ENS から解決する。Agent の公開（Creator 所有）にも同じ経路を使う。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        raise RuntimeError("RPC 未設定のため calldata を生成できません")
    w3 = _w3()
    reg = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=ETH_REGISTRY_ABI)
    parent_label = company_name.removesuffix(".eth")
    sub = reg.functions.getSubregistry(parent_label).call()
    if int(sub, 16) == 0:
        raise RuntimeError(f"{company_name} にサブレジストリがありません。`ens subregistry deploy {company_name} --chain sepolia` で作成してください")
    resolver_addr, _, _ = resolve_v2(w3, company_name)
    if resolver_addr is None:
        raise RuntimeError(f"{company_name} にリゾルバが設定されていません")
    subreg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI)
    resolver = w3.eth.contract(address=resolver_addr, abi=RESOLVER_ABI)
    expiry = int(time.time()) + ONE_YEAR
    txs = []
    if int(subreg.functions.getResolver(label).call(), 16) == 0:
        txs.append({"to": sub, "data": subreg.encode_abi("register", args=[label, Web3.to_checksum_address(owner), "0x" + "00" * 20, resolver_addr, V2_DEFAULT_OWNER_ROLE_BITMAP, expiry]), "label": f"{label}.{company_name} を発行"})
    node = namehash(f"{label}.{company_name}")
    calls = [bytes.fromhex(resolver.encode_abi("setAddr", args=[node, Web3.to_checksum_address(owner)])[2:])]
    calls += [bytes.fromhex(resolver.encode_abi("setText", args=[node, k, v])[2:]) for k, v in texts.items()]
    txs.append({"to": resolver_addr, "data": resolver.encode_abi("multicall", args=[calls]), "label": "プロフィール（text record）を書き込み"})
    return txs


def records_calldata_for(*, name: str, texts: dict[str, str], addr: str | None = None) -> list[dict]:
    """名前の所有者が自分のウォレットで送る、text record（と addr）の書き込み calldata（multicall 1 本）。
    Creator 所有の Agent の編集（D4）で使う。リゾルバは ENS から解決する。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        raise RuntimeError("RPC 未設定のため calldata を生成できません")
    w3 = _w3()
    resolver_addr, _, _ = resolve_v2(w3, name)
    if resolver_addr is None:
        raise RuntimeError(f"{name} にリゾルバが設定されていません")
    r = w3.eth.contract(address=resolver_addr, abi=RESOLVER_ABI)
    calls = _records_calldata(w3, namehash(name), texts, addr, r)
    return [{"to": resolver_addr, "data": r.encode_abi("multicall", args=[calls]), "label": "プロフィール（text record）を更新"}]


# ---------------------------------------------------------------- EAC: 役割の確認


_roles_cache: dict[str, tuple[float, list[dict]]] = {}


def agent_roles(name: str, label: str, ttl: float = 300.0) -> list[dict]:
    """agent_roles_uncached の 5 分キャッシュ。権限表は 15〜25 回の eth_call になるため、Agent 詳細の表示ごとには読まない。"""
    hit = _roles_cache.get(name)
    if hit and time.time() - hit[0] < ttl:
        return [dict(r) for r in hit[1]]
    out = agent_roles_uncached(name, label)
    if out and not any(r.get("role") == "error" for r in out):
        _roles_cache[name] = (time.time(), [dict(r) for r in out])
    return out


def agent_roles_uncached(name: str, label: str) -> list[dict]:
    """Agent の名前まわりの EAC 役割をオンチェーンから読む（画面の権限表と検証用）。
    設計:
      Owner      … 共有リゾルバの root admin。<agent> のプロフィールと subname 発行
      Reputation … reputation.<agent> の所有者で、Reputation リゾルバの root admin。評価キーはそこにしか書けない
      Project    … <agent> サブレジストリの ROLE_REGISTRAR（ルート役割だがこの Agent に閉じる）と Project リゾルバの root admin
    verified = 「できる」が True かつ「できない」が False。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return []
    w3 = _w3()
    addrs = role_addresses()
    rep, proj = addrs["reputation"], addrs["project"]
    T, A = RESOLVER_ROLE_SET_TEXT, RESOLVER_ROLE_SET_ADDR
    out = []
    try:
        # 名前から親レジストリ・共有リゾルバ・Owner（名前の所有者）を決める。platform なら ops 鍵、creator なら Creator のウォレット
        parent_reg = subregistry_of(w3, name.split(".", 1)[1])
        if parent_reg is None:
            return []
        main_addr, _, _ = resolve_v2(w3, name)
        owner = owner_of(w3, name) or addrs["owner"]
        if not main_addr or not owner:
            return []
        sub = parent_reg.functions.getSubregistry(label).call()
        has_sub = bool(int(sub, 16))
        sub_reg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI) if has_sub else None
        rep_res_addr = sub_reg.functions.getResolver("reputation").call() if sub_reg else "0x" + "00" * 20
        rep_res_a = Web3.to_checksum_address(s.ens_reputation_resolver) if s.ens_reputation_resolver else None
        proj_res_a = Web3.to_checksum_address(s.ens_project_resolver) if s.ens_project_resolver else None
        eac = w3.eth.contract(abi=EAC_ABI)

        # hasRootRoles の問い合わせを全部集めて 1 回の eth_call にする（従来は 15〜25 回直列）
        queries: dict[str, tuple[str, int, str]] = {
            "main.T.owner": (main_addr, T, owner), "main.TA.owner": (main_addr, T | A, owner),
            "main.T.rep": (main_addr, T, rep), "main.T.proj": (main_addr, T, proj),
            "parent.REG.proj": (parent_reg.address, REGISTRY_ROLE_REGISTRAR, proj),
        }
        if rep_res_a:
            queries |= {"repres.T.owner": (rep_res_a, T, owner), "repres.T.rep": (rep_res_a, T, rep)}
        if proj_res_a:
            queries |= {"projres.T.proj": (proj_res_a, T, proj)}
        if has_sub:
            queries |= {"sub.REG.rep": (sub, REGISTRY_ROLE_REGISTRAR, rep), "sub.REG.proj": (sub, REGISTRY_ROLE_REGISTRAR, proj), "sub.SETRES.proj": (sub, ROLE_SET_RESOLVER, proj)}
        names = list(queries)
        results = multicall(w3, [(queries[k][0], eac.encode_abi("hasRootRoles", args=[queries[k][1], Web3.to_checksum_address(queries[k][2])])) for k in names])
        v: dict[str, bool | None] = {k: decode_bool(ok, raw) for k, (ok, raw) in zip(names, results, strict=True)}
        g = v.get  # 未問い合わせ（リゾルバ未設定など）は None

        out.append({
            "role": "Owner（PM Agent / Creator）", "account": owner, "where": f"{name} → 共有リゾルバ {main_addr[:10]}…",
            "can": "プロフィール（description, codrea.agent.*）の更新、subname の発行", "cannot": "reputation.* と project-* のレコード更新（別リゾルバ）",
            "verified": bool(g("main.TA.owner") and rep_res_a and not g("repres.T.owner")),
            "checks": {"main.setText": g("main.T.owner"), "reputation-resolver.setText": g("repres.T.owner")},
        })
        out.append({
            "role": "Reputation", "account": rep, "where": f"{reputation_name_of(name)} → Reputation リゾルバ {s.ens_reputation_resolver[:10]}…",
            "can": "codrea.agent.rating / reviews / completed の更新（reputation subname のみ）", "cannot": "Agent のプロフィール更新、subname の発行",
            "subname": reputation_name_of(name) if int(rep_res_addr, 16) else None,
            "verified": bool(rep_res_a and g("repres.T.rep") and not g("main.T.rep") and int(rep_res_addr, 16) and rep.lower() != owner.lower()),
            "checks": {"reputation-resolver.setText": g("repres.T.rep"), "main.setText": g("main.T.rep"),
                       "subregistry.register": g("sub.REG.rep"), "reputation subname resolver set": bool(int(rep_res_addr, 16))},
        })
        out.append({
            "role": "Project Agent", "account": proj, "where": f"{name} サブレジストリ {sub[:10] if has_sub else '-'}… / Project リゾルバ {s.ens_project_resolver[:10]}…",
            "can": "project-* subname の発行（ROLE_REGISTRAR）と codrea.project.* の更新（Project リゾルバ）", "cannot": "Agent のリゾルバ変更、プロフィールや評価の更新、親名直下への発行",
            "subregistry": sub if has_sub else None,
            "verified": bool(has_sub and g("sub.REG.proj") and not g("sub.SETRES.proj") and proj_res_a and g("projres.T.proj") and not g("main.T.proj")
                             and not g("parent.REG.proj") and proj.lower() != owner.lower()),
            "checks": {"agent-subregistry.register": g("sub.REG.proj"), "agent-subregistry.setResolver": g("sub.SETRES.proj"),
                       "project-resolver.setText": g("projres.T.proj"), "main.setText": g("main.T.proj"), "choice.eth-subregistry.register": g("parent.REG.proj")},
        })
    except Exception as e:  # noqa: BLE001
        out.append({"role": "error", "error": str(e)[:200]})
    return out


# ---------------------------------------------------------------- セルフサービス: 名前の所有者が自分でリゾルバとサブレジストリを用意する

FACTORY_ABI = [{"type": "function", "name": "deployProxy", "stateMutability": "nonpayable",
                "inputs": [{"name": "implementation", "type": "address"}, {"name": "salt", "type": "uint256"}, {"name": "data", "type": "bytes"}],
                "outputs": [{"type": "address"}]}]
RESOLVER_INIT_ABI = [{"type": "function", "name": "initialize", "stateMutability": "nonpayable",
                      "inputs": [{"name": "admin", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "setters", "type": "bytes[]"}], "outputs": []}]
USER_REGISTRY_INIT_ABI = [{"type": "function", "name": "initialize", "stateMutability": "nonpayable",
                           "inputs": [{"name": "rootAccount", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}], "outputs": []}]


def setup_calldata(*, name: str, owner: str) -> dict:
    """登録済みの .eth 2LD に、所有者自身のウォレットで OwnedResolver と UserRegistry（サブレジストリ）を用意する calldata。
    scripts/ens_setup.py の 1・3 段階を、Creator / 会社がセルフサービスで実行できるようにしたもの。
    deployProxy は VerifiableFactory の CREATE2 なので、送信前に eth_call で予定アドレスが分かる（送信者 = owner で予測する）。
    既に揃っている段階はスキップし、txs が空なら準備完了。"""
    from eth_abi import encode

    s = get_settings()
    if not s.sepolia_rpc_url:
        raise ValueError("RPC 未設定のため calldata を生成できません")
    labels = name.lower().split(".")
    if len(labels) != 2 or labels[1] != "eth":
        raise ValueError("セルフサービス準備は <label>.eth（2LD）のみ対応です")
    label = labels[0]
    owner = Web3.to_checksum_address(owner)
    w3 = _w3()
    eth_registry = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=V2_REGISTRY_ABI)
    status, _, cur_owner, token_id, _ = eth_registry.functions.getState(_labelhash_int(label)).call()
    if status != 2:
        raise ValueError(f"{name} は ENSv2（Sepolia）に登録されていません。先に登録してください")
    if cur_owner.lower() != owner.lower():
        raise ValueError(f"{name} の所有者（{cur_owner}）が接続中のウォレットと一致しません")
    factory = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_verifiable_factory), abi=FACTORY_ABI)
    txs: list[dict] = []
    out: dict = {"name": name, "owner": owner, "token_id": str(token_id)}

    # 1. リゾルバ（所有者が root admin の OwnedResolver = Permissioned Resolver）
    resolver = eth_registry.functions.getResolver(label).call()
    if int(resolver, 16):
        out["resolver"] = {"address": resolver, "exists": True}
    else:
        # salt は名前ごとに変える（以前は owner だけだったため、同じウォレットの 2 つ目の名前で CREATE2 のアドレスが衝突し deployProxy の eth_call が revert した）
        salt = int.from_bytes(keccak(encode(["bytes32", "address", "bytes32"], [keccak(text="OwnedResolver"), owner, namehash(name)])), "big")
        init = w3.eth.contract(abi=RESOLVER_INIT_ABI).encode_abi("initialize", args=[owner, ALL_ROLES, []])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_resolver_impl), salt, bytes.fromhex(init[2:]))
        try:
            predicted = fn.call({"from": owner})
        except ContractLogicError as e:
            raise ValueError(f"{name} 用のリゾルバの予定アドレスを計算できませんでした（同じ salt で既にデプロイ済みの可能性）。ens_setup.py か ens-cli で用意してください: {e}") from e
        deployed = w3.eth.get_code(predicted) not in (b"", b"\x00")
        if not deployed:
            txs.append({"to": factory.address, "data": factory.encode_abi("deployProxy", args=[Web3.to_checksum_address(s.ensv2_resolver_impl), salt, bytes.fromhex(init[2:])]),
                        "label": f"OwnedResolver をデプロイ（admin = あなた）→ {predicted}"})
        txs.append({"to": eth_registry.address, "data": eth_registry.encode_abi("setResolver", args=[token_id, predicted]), "label": f"{name} のリゾルバを設定"})
        out["resolver"] = {"address": predicted, "exists": deployed}
        resolver = predicted

    # 2. サブレジストリ（所有者が root の UserRegistry）
    sub = eth_registry.functions.getSubregistry(label).call()
    if int(sub, 16):
        out["subregistry"] = {"address": sub, "exists": True}
    else:
        salt = int.from_bytes(keccak(encode(["bytes32", "bytes32", "uint256"], [keccak(text="UserRegistry"), namehash(name), 0])), "big")
        init = w3.eth.contract(abi=USER_REGISTRY_INIT_ABI).encode_abi("initialize", args=[owner, ALL_ROLES])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:]))
        try:
            predicted = fn.call({"from": owner})
        except ContractLogicError as e:
            raise ValueError(f"{name} 用のサブレジストリの予定アドレスを計算できませんでした（同じ salt で既にデプロイ済みの可能性）: {e}") from e
        deployed = w3.eth.get_code(predicted) not in (b"", b"\x00")
        if not deployed:
            txs.append({"to": factory.address, "data": factory.encode_abi("deployProxy", args=[Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:])]),
                        "label": f"UserRegistry（サブレジストリ）をデプロイ（root = あなた）→ {predicted}"})
        txs.append({"to": eth_registry.address, "data": eth_registry.encode_abi("setSubregistry", args=[token_id, predicted]), "label": f"{name} にサブレジストリを設定"})
        out["subregistry"] = {"address": predicted, "exists": deployed}

    out["txs"] = txs
    out["ready"] = not txs
    return out



# ---------------------------------------------------------------- Creator 所有の Agent（<label>.<creator>.eth）: Creator が署名する名前空間の構築


def agent_namespace_calldata(*, name: str, owner: str, payout_address: str, texts: dict[str, str], subagents: list[dict] | bool = True) -> dict:
    """Creator 自身の .eth の下に PM Agent を「名前空間」として公開するための tx 群（すべて Creator のウォレットが署名）。
      1. register <label>（親のサブレジストリ。owner = Creator、resolver = 親のリゾルバ）
      2. multicall setAddr / setText（プロフィール。評価キーは reputation subname 側）
      3. deployProxy UserRegistry（Agent のサブレジストリ。root = Creator）
      4. setSubregistry（親のサブレジストリに設定。anyId = labelhash）
      5. grantRootRoles(ROLE_REGISTRAR, Project 鍵)（EAC: Project 鍵は project-* の発行だけ。この Agent に閉じる）
      6. register reputation（owner = Reputation 鍵、resolver = Reputation リゾルバ。評価は Reputation 鍵だけが書ける）
      7. register designer / frontend / backend / qa（専門 AI エージェント）+ multicall record（任意）
    platform の publish_agent と同じ構造を Creator 側の鍵で組み立てる。揃っている段階はスキップ。"""
    from eth_abi import encode

    s = get_settings()
    if not s.sepolia_rpc_url:
        raise RuntimeError("RPC 未設定のため calldata を生成できません")
    w3 = _w3()
    owner = Web3.to_checksum_address(owner)
    label, parent_name = name.split(".", 1)
    parent_reg = subregistry_of(w3, parent_name)
    if parent_reg is None:
        raise RuntimeError(f"{parent_name} にサブレジストリがありません（/ens/setup-calldata で用意できます）")
    parent_resolver_addr, _, _ = resolve_v2(w3, parent_name)
    if parent_resolver_addr is None:
        raise RuntimeError(f"{parent_name} にリゾルバが設定されていません（/ens/setup-calldata で用意できます）")
    pres = w3.eth.contract(address=parent_resolver_addr, abi=RESOLVER_ABI)
    expiry = int(time.time()) + ONE_YEAR
    zero = "0x" + "00" * 20
    txs: list[dict] = []
    node = namehash(name)

    # 1. register
    status, _, cur_owner, _, _ = parent_reg.functions.getState(_labelhash_int(label)).call()
    if status == 2:
        if cur_owner.lower() != owner.lower():
            raise RuntimeError(f"{name} は既に別の所有者（{cur_owner}）が登録しています")
    else:
        txs.append({"to": parent_reg.address, "data": parent_reg.encode_abi("register", args=[label, owner, zero, parent_resolver_addr, V2_DEFAULT_OWNER_ROLE_BITMAP, expiry]), "label": f"{name} を発行"})
    # 2. profile
    main_texts = {k: v for k, v in texts.items() if k not in REPUTATION_KEYS} if s.ens_reputation_resolver else texts
    txs.append({"to": parent_resolver_addr, "data": pres.encode_abi("multicall", args=[_records_calldata(w3, node, main_texts, payout_address, pres)]), "label": "プロフィール（text record）を書き込み"})
    # 3. agent subregistry
    factory = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_verifiable_factory), abi=FACTORY_ABI)
    existing_sub = parent_reg.functions.getSubregistry(label).call()
    if int(existing_sub, 16):
        sub_addr = existing_sub
    else:
        salt = int.from_bytes(keccak(encode(["bytes32", "bytes32", "uint256"], [keccak(text="UserRegistry"), node, 0])), "big")
        init = w3.eth.contract(abi=USER_REGISTRY_INIT_ABI).encode_abi("initialize", args=[owner, ALL_ROLES])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:]))
        sub_addr = fn.call({"from": owner})
        if w3.eth.get_code(sub_addr) in (b"", b"\x00"):
            txs.append({"to": factory.address, "data": factory.encode_abi("deployProxy", args=[Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:])]),
                        "label": f"Agent のサブレジストリをデプロイ（root = あなた）→ {sub_addr}"})
        txs.append({"to": parent_reg.address, "data": parent_reg.encode_abi("setSubregistry", args=[_labelhash_int(label), sub_addr]), "label": f"{name} にサブレジストリを設定（Agent を名前空間にする）"})
    sub_reg = w3.eth.contract(address=sub_addr, abi=V2_REGISTRY_ABI)
    sub_eac = w3.eth.contract(address=sub_addr, abi=EAC_ABI)
    deployed = int(existing_sub, 16) != 0
    # 5. Project 鍵に ROLE_REGISTRAR
    project = _account("project").address if s.server_private_key else None
    if project and s.ens_project_resolver:
        if not (deployed and sub_eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, project).call()):
            txs.append({"to": sub_addr, "data": sub_eac.encode_abi("grantRootRoles", args=[REGISTRY_ROLE_REGISTRAR, project]), "label": f"Project 鍵（{project[:8]}…）に project subname の発行権限だけを付与（EAC ROLE_REGISTRAR）"})
    # 6. reputation subname
    rep = _account("reputation").address if s.server_private_key else None
    if rep and s.ens_reputation_resolver:
        if not (deployed and int(sub_reg.functions.getResolver("reputation").call(), 16)):
            txs.append({"to": sub_addr, "data": sub_reg.encode_abi("register", args=["reputation", rep, zero, Web3.to_checksum_address(s.ens_reputation_resolver), V2_DEFAULT_OWNER_ROLE_BITMAP, expiry]),
                        "label": f"reputation.{name} を発行（所有者 = Reputation 鍵、Reputation リゾルバ）"})
    # 7. subagents（所有者が定義した一覧。True なら既定の 4 つ、False / [] なら発行しない）
    subs = DEFAULT_SUBAGENTS if subagents is True else ([] if subagents is False else subagents)
    if subs:
        calls: list[bytes] = []
        for sub in subs:
            role = sub["role"]
            if deployed and int(sub_reg.functions.getResolver(role).call(), 16):
                continue
            txs.append({"to": sub_addr, "data": sub_reg.encode_abi("register", args=[role, owner, zero, parent_resolver_addr, V2_DEFAULT_OWNER_ROLE_BITMAP, expiry]), "label": f"{role}.{name} を発行（専門 AI エージェント）"})
            calls += _records_calldata(w3, namehash(f"{role}.{name}"), subagent_texts(sub, name), None, pres)
        if calls:
            txs.append({"to": parent_resolver_addr, "data": pres.encode_abi("multicall", args=[calls]), "label": "専門 AI エージェントの record を書き込み"})
    return {"name": name, "owner": owner, "subregistry": sub_addr, "reputation_name": reputation_name_of(name) if rep and s.ens_reputation_resolver else None,
            "project_key": project, "reputation_key": rep, "txs": txs}


def verify_agent_namespace(*, name: str, roles: list[str] | None = None) -> dict:
    """Creator が tx を送った後の確認。サブレジストリ・Project 鍵の ROLE_REGISTRAR・reputation subname・専門 Agent をオンチェーンで読む。"""
    s = get_settings()
    w3 = _w3()
    reg = subregistry_of(w3, name)
    out = {"subregistry": reg.address if reg is not None else None, "project_registrar": False, "reputation": False, "subagents": []}
    if reg is None:
        return out
    eac = w3.eth.contract(address=reg.address, abi=EAC_ABI)
    if s.server_private_key and s.ens_project_resolver:
        out["project_registrar"] = bool(eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, _account("project").address).call())
    out["reputation"] = bool(int(reg.functions.getResolver("reputation").call(), 16))
    out["subagents"] = [r for r in (roles if roles is not None else SUBAGENT_ROLES) if int(reg.functions.getResolver(r).call(), 16)]
    return out


# ---------------------------------------------------------------- 利用者が自分のウォレットで .eth（2LD）を登録する

REGISTRAR_ABI = [
    {"type": "function", "name": "isAvailable", "stateMutability": "view", "inputs": [{"name": "label", "type": "string"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "getRegisterPrice", "stateMutability": "view",
     "inputs": [{"name": "label", "type": "string"}, {"name": "duration", "type": "uint64"}, {"name": "paymentToken", "type": "address"}],
     "outputs": [{"name": "base", "type": "uint256"}, {"name": "premium", "type": "uint256"}]},
    {"type": "function", "name": "makeCommitment", "stateMutability": "view",
     "inputs": [{"name": "label", "type": "string"}, {"name": "owner", "type": "address"}, {"name": "secret", "type": "bytes32"}, {"name": "subregistry", "type": "address"},
                {"name": "resolver", "type": "address"}, {"name": "duration", "type": "uint64"}, {"name": "referrer", "type": "bytes32"}],
     "outputs": [{"type": "bytes32"}]},
    {"type": "function", "name": "commit", "stateMutability": "nonpayable", "inputs": [{"name": "commitment", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "register", "stateMutability": "nonpayable",
     "inputs": [{"name": "label", "type": "string"}, {"name": "owner", "type": "address"}, {"name": "secret", "type": "bytes32"}, {"name": "subregistry", "type": "address"},
                {"name": "resolver", "type": "address"}, {"name": "duration", "type": "uint64"}, {"name": "paymentToken", "type": "address"}, {"name": "referrer", "type": "bytes32"}],
     "outputs": [{"name": "tokenId", "type": "uint256"}]},
]
ERC20_MIN_ABI = [
    {"type": "function", "name": "mint", "stateMutability": "nonpayable", "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
    {"type": "function", "name": "allowance", "stateMutability": "view", "inputs": [{"name": "o", "type": "address"}, {"name": "s", "type": "address"}], "outputs": [{"type": "uint256"}]},
]
MIN_COMMITMENT_AGE = 60  # ENSv2 Sepolia beta の ETHRegistrar（秒）


def register_calldata(*, name: str, owner: str, phase: str, secret: str | None = None) -> dict:
    """利用者のウォレットで .eth（2LD）を登録する calldata。commit / reveal の 2 段階。
      phase=commit  … テスト用トークンの mint（不足分）・approve（不足分）・commit。secret を返す（reveal で必要）
      phase=register… commit から 60 秒以上あけて register（resolver / subregistry は 0。続けて setup-calldata で用意する）
    登録料は ENSv2 beta のテスト用トークン（誰でも mint 可）。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        raise ValueError("RPC 未設定のため calldata を生成できません")
    labels = name.lower().split(".")
    if len(labels) != 2 or labels[1] != "eth":
        raise ValueError("登録できるのは <label>.eth（2LD）だけです")
    label = labels[0]
    owner = Web3.to_checksum_address(owner)
    w3 = _w3()
    registrar = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_registrar), abi=REGISTRAR_ABI)
    token = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_payment_token), abi=ERC20_MIN_ABI)
    zero = "0x" + "00" * 20
    if not registrar.functions.isAvailable(label).call():
        raise ValueError(f"{name} は取得できません（登録済みか予約済み）")
    base, premium = registrar.functions.getRegisterPrice(label, ONE_YEAR, token.address).call()
    price = base + premium
    out: dict = {"name": name, "owner": owner, "price": str(price), "payment_token": token.address, "duration": ONE_YEAR, "min_commitment_age": MIN_COMMITMENT_AGE, "txs": []}
    if phase == "commit":
        secret_b = secrets.token_bytes(32)
        bal = token.functions.balanceOf(owner).call()
        if bal < price:
            out["txs"].append({"to": token.address, "data": token.encode_abi("mint", args=[owner, price - bal]), "label": f"登録料のテスト用トークンを mint（{price - bal}）"})
        if token.functions.allowance(owner, registrar.address).call() < price:
            out["txs"].append({"to": token.address, "data": token.encode_abi("approve", args=[registrar.address, price]), "label": "登録料の approve"})
        commitment = registrar.functions.makeCommitment(label, owner, secret_b, zero, zero, ONE_YEAR, b"\x00" * 32).call()
        out["txs"].append({"to": registrar.address, "data": registrar.encode_abi("commit", args=[commitment]), "label": f"{name} の commit（先取り防止。60 秒後に register）"})
        out["secret"] = "0x" + secret_b.hex()
        return out
    if phase == "register":
        if not secret or not secret.startswith("0x") or len(secret) != 66:
            raise ValueError("commit で受け取った secret が必要です")
        secret_b = bytes.fromhex(secret[2:])
        out["txs"].append({"to": registrar.address, "data": registrar.encode_abi("register", args=[label, owner, secret_b, zero, zero, ONE_YEAR, token.address, b"\x00" * 32]),
                           "label": f"{name} を登録（reveal）"})
        return out
    raise ValueError("phase は commit または register")
