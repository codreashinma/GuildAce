"""ENSv2（Sepolia beta）連携。
- 公開: 親名 choice.eth のサブレジストリに subname を register し、OwnedResolver に text record を書く
- 更新: 評価・完了数などの text record を更新
- 読み取り: UniversalResolver 経由で text record を読む
ENS_WRITE_ENABLED=false のときはモック（tx hash を生成せず ens_name だけ確定）。

役割ビットマップ等は ensdomains/ens-cli の v2.ts に合わせている。"""

import secrets
import time

from eth_utils import keccak
from web3 import Web3

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
SUBAGENT_ROLES = ["designer", "frontend", "backend", "qa"]  # PM Agent 配下の専門 AI エージェント（Agent 名前空間の subname）
SUBAGENT_KEYS = ["description", "codrea.agent.role", "codrea.agent.parent", "codrea.agent.kind"]
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


def resolve_v2(w3: Web3, name: str) -> tuple[str | None, str | None, str | None]:
    """ENSv2 のレジストリを .eth から順にたどり、(resolver, 親レジストリ, 最終ラベル) を返す。
    Universal Resolver が v2 名を解決しない期間があるため、レジストリを直接歩く。"""
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


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(get_settings().sepolia_rpc_url))


def _account(role: str = "owner"):
    """署名鍵。owner = 運用ウォレット（名前の所有者）、reputation / project = EAC で限定された役割鍵。
    役割鍵が未設定なら owner にフォールバックする（役割分離なしの MVP 動作）。"""
    from eth_account import Account

    s = get_settings()
    key = {"owner": s.server_private_key, "reputation": s.reputation_private_key or s.server_private_key, "project": s.project_private_key or s.server_private_key}[role]
    return Account.from_key(key)


def role_addresses() -> dict[str, str | None]:
    s = get_settings()
    return {r: (_account(r).address if s.server_private_key else None) for r in ("owner", "reputation", "project")}


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


def publish_agent(*, label: str, payout_address: str, texts: dict[str, str]) -> tuple[str, str]:
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
    calls: list[bytes] = []
    for role in SUBAGENT_ROLES:
        if int(sub_reg.functions.getResolver(role).call(), 16) == 0:
            _send(w3, sub_reg.functions.register(role, acct.address, "0x" + "00" * 20, Web3.to_checksum_address(s.ens_owned_resolver), V2_DEFAULT_OWNER_ROLE_BITMAP, expiry))
            calls += _records_calldata(w3, namehash(f"{role}.{name}"), {
                "description": f"{texts.get('description', '')[:60]} の {role} 担当 AI エージェント", "codrea.agent.role": role, "codrea.agent.parent": name, "codrea.agent.kind": "ai",
            }, None)
    if calls:
        _send(w3, _resolver(w3).functions.multicall(calls))
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


def publish_project(*, agent_label: str, project_label: str, texts: dict[str, str]) -> tuple[str, str]:
    """案件ごとの subname（project-<n>.<agent>.choice.eth）を発行し、record を書く（FR-027）。"""
    s = get_settings()
    name = f"{project_label}.{agent_ens_name(agent_label)}"
    if not s.ens_write_enabled:
        return name, "0xmock" + secrets.token_hex(29)
    w3 = _w3()
    project = _account("project")
    parent_reg = _subregistry(w3)  # choice.eth のサブレジストリ（Agent を登録している）
    sub = parent_reg.functions.getSubregistry(agent_label).call()
    if int(sub, 16) == 0:
        raise RuntimeError(f"{agent_ens_name(agent_label)} にサブレジストリがありません（Agent の公開時に作られます）")
    reg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI)
    # Project 鍵は ROLE_REGISTRAR しか持たないので、register と codrea.project.* の setText 以外は revert する
    pr = _role_resolver(w3, "project")
    if int(reg.functions.getResolver(project_label).call(), 16) == 0:
        _send(w3, reg.functions.register(project_label, project.address, "0x" + "00" * 20, pr.address, V2_DEFAULT_OWNER_ROLE_BITMAP, int(time.time()) + ONE_YEAR), role="project")
    node = namehash(name)
    texts = {k: v for k, v in texts.items() if k in PROJECT_KEYS}
    tx = _send(w3, pr.functions.multicall(_records_calldata(w3, node, texts, None, pr)), role="project")
    return name, tx


def update_texts(label: str, texts: dict[str, str]) -> str | None:
    """text record の更新。評価キーだけなら Reputation 鍵で署名する（EAC でそのキー以外は書けない）。"""
    s = get_settings()
    if not s.ens_write_enabled:
        return None
    w3 = _w3()
    if texts and all(k in REPUTATION_KEYS for k in texts) and s.ens_reputation_resolver:
        rr = _role_resolver(w3, "reputation")
        return _send(w3, rr.functions.multicall(_records_calldata(w3, namehash(reputation_name(label)), texts, None, rr)), role="reputation")
    node = namehash(agent_ens_name(label))
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
        r = w3.eth.contract(address=resolver_addr, abi=RESOLVER_ABI)
        node = namehash(name)
        out = {}
        for k in keys or PROFILE_KEYS:
            v = r.functions.text(node, k).call()
            if v:
                out[k] = v
        _read_cache[ck] = (time.time(), dict(out))
        return out
    except Exception:
        return {}


# ---------------------------------------------------------------- 会社所有の名前（会社管理者が署名する）

ETH_REGISTRY_ABI = V2_REGISTRY_ABI


def _labelhash_int(label: str) -> int:
    return int.from_bytes(keccak(text=label), "big")


def name_owner(name: str) -> str | None:
    """ENSv2 の .eth 2LD の所有者。RPC 未設定・取得失敗は None。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return None
    try:
        w3 = _w3()
        reg = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=ETH_REGISTRY_ABI)
        status, _, owner, _, _ = reg.functions.getState(_labelhash_int(name.removesuffix(".eth"))).call()
        return owner if status == 2 else None
    except Exception:
        return None


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


# ---------------------------------------------------------------- EAC: 役割の確認


def agent_roles(name: str, label: str) -> list[dict]:
    """Agent の名前まわりの EAC 役割をオンチェーンから読む（画面の権限表と検証用）。
    設計:
      Owner      … 共有リゾルバの root admin。<agent> のプロフィールと subname 発行
      Reputation … reputation.<agent> の所有者で、Reputation リゾルバの root admin。評価キーはそこにしか書けない
      Project    … <agent> サブレジストリの ROLE_REGISTRAR（ルート役割だがこの Agent に閉じる）と Project リゾルバの root admin
    verified = 「できる」が True かつ「できない」が False。"""
    s = get_settings()
    if not s.sepolia_rpc_url or not s.ens_owned_resolver:
        return []
    w3 = _w3()
    addrs = role_addresses()
    owner, rep, proj = addrs["owner"], addrs["reputation"], addrs["project"]
    T, A = RESOLVER_ROLE_SET_TEXT, RESOLVER_ROLE_SET_ADDR
    main = w3.eth.contract(address=Web3.to_checksum_address(s.ens_owned_resolver), abi=EAC_ABI)
    out = []
    try:
        parent_reg = _subregistry(w3)
        sub = parent_reg.functions.getSubregistry(label).call()
        sub_eac = w3.eth.contract(address=sub, abi=EAC_ABI) if int(sub, 16) else None
        sub_reg = w3.eth.contract(address=sub, abi=V2_REGISTRY_ABI) if int(sub, 16) else None
        rep_res_addr = sub_reg.functions.getResolver("reputation").call() if sub_reg else "0x" + "00" * 20
        rep_res = w3.eth.contract(address=Web3.to_checksum_address(s.ens_reputation_resolver), abi=EAC_ABI) if s.ens_reputation_resolver else None
        proj_res = w3.eth.contract(address=Web3.to_checksum_address(s.ens_project_resolver), abi=EAC_ABI) if s.ens_project_resolver else None

        out.append({
            "role": "Owner（PM Agent / Creator）", "account": owner, "where": f"{name} → 共有リゾルバ {s.ens_owned_resolver[:10]}…",
            "can": "プロフィール（description, codrea.agent.*）の更新、subname の発行", "cannot": "reputation.* と project-* のレコード更新（別リゾルバ）",
            "verified": bool(main.functions.hasRootRoles(T | A, owner).call() and rep_res and not rep_res.functions.hasRootRoles(T, owner).call()),
            "checks": {"main.setText": main.functions.hasRootRoles(T, owner).call(), "reputation-resolver.setText": rep_res.functions.hasRootRoles(T, owner).call() if rep_res else None},
        })
        out.append({
            "role": "Reputation", "account": rep, "where": f"{reputation_name(label)} → Reputation リゾルバ {s.ens_reputation_resolver[:10]}…",
            "can": "codrea.agent.rating / reviews / completed の更新（reputation subname のみ）", "cannot": "Agent のプロフィール更新、subname の発行",
            "subname": reputation_name(label) if int(rep_res_addr, 16) else None,
            "verified": bool(rep_res and rep_res.functions.hasRootRoles(T, rep).call() and not main.functions.hasRootRoles(T, rep).call() and int(rep_res_addr, 16) and rep.lower() != owner.lower()),
            "checks": {"reputation-resolver.setText": rep_res.functions.hasRootRoles(T, rep).call() if rep_res else None, "main.setText": main.functions.hasRootRoles(T, rep).call(),
                       "subregistry.register": sub_eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, rep).call() if sub_eac else None, "reputation subname resolver set": bool(int(rep_res_addr, 16))},
        })
        out.append({
            "role": "Project Agent", "account": proj, "where": f"{name} サブレジストリ {sub[:10] if int(sub, 16) else '-'}… / Project リゾルバ {s.ens_project_resolver[:10]}…",
            "can": "project-* subname の発行（ROLE_REGISTRAR）と codrea.project.* の更新（Project リゾルバ）", "cannot": "Agent のリゾルバ変更、プロフィールや評価の更新、choice.eth 直下への発行",
            "subregistry": sub if int(sub, 16) else None,
            "verified": bool(sub_eac and sub_eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, proj).call() and not sub_eac.functions.hasRootRoles(ROLE_SET_RESOLVER, proj).call()
                             and proj_res and proj_res.functions.hasRootRoles(T, proj).call() and not main.functions.hasRootRoles(T, proj).call()
                             and not w3.eth.contract(address=parent_reg.address, abi=EAC_ABI).functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, proj).call() and proj.lower() != owner.lower()),
            "checks": {"agent-subregistry.register": sub_eac.functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, proj).call() if sub_eac else None,
                       "agent-subregistry.setResolver": sub_eac.functions.hasRootRoles(ROLE_SET_RESOLVER, proj).call() if sub_eac else None,
                       "project-resolver.setText": proj_res.functions.hasRootRoles(T, proj).call() if proj_res else None,
                       "main.setText": main.functions.hasRootRoles(T, proj).call(),
                       "choice.eth-subregistry.register": w3.eth.contract(address=parent_reg.address, abi=EAC_ABI).functions.hasRootRoles(REGISTRY_ROLE_REGISTRAR, proj).call()},
        })
    except Exception as e:  # noqa: BLE001
        out.append({"role": "error", "error": str(e)[:200]})
    return out
