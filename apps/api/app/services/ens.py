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

PROFILE_KEYS = ["description", "avatar", "url", "agent.category", "agent.fee_bps", "agent.creator", "agent.endpoint", "agent.rating", "agent.reviews", "agent.completed"]


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


def agent_ens_name(label: str) -> str:
    return f"{label}.{get_settings().ens_parent_name}"


def _w3() -> Web3:
    return Web3(Web3.HTTPProvider(get_settings().sepolia_rpc_url))


def _account():
    from eth_account import Account

    return Account.from_key(get_settings().server_private_key)


def _send(w3: Web3, fn) -> str:
    s = get_settings()
    acct = _account()
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


def _subregistry(w3: Web3):
    s = get_settings()
    return w3.eth.contract(address=Web3.to_checksum_address(s.ens_parent_subregistry), abi=V2_REGISTRY_ABI)


def _records_calldata(w3: Web3, node: bytes, texts: dict[str, str], addr: str | None) -> list[bytes]:
    r = _resolver(w3)
    data: list[bytes] = []
    if addr:
        data.append(bytes.fromhex(r.encode_abi("setAddr", args=[node, Web3.to_checksum_address(addr)])[2:]))
    for k, v in texts.items():
        data.append(bytes.fromhex(r.encode_abi("setText", args=[node, k, v])[2:]))
    return data


def publish_agent(*, label: str, payout_address: str, texts: dict[str, str]) -> tuple[str, str]:
    """subname を発行してプロフィールを書く。(ens_name, tx_hash) を返す。"""
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
    tx = _send(w3, _resolver(w3).functions.multicall(_records_calldata(w3, node, texts, payout_address)))
    return name, tx


def update_texts(label: str, texts: dict[str, str]) -> str | None:
    s = get_settings()
    if not s.ens_write_enabled:
        return None
    w3 = _w3()
    node = namehash(agent_ens_name(label))
    return _send(w3, _resolver(w3).functions.multicall(_records_calldata(w3, node, texts, None)))


def read_texts(name: str, keys: list[str] | None = None) -> dict[str, str]:
    """UniversalResolver で resolver を見つけ、text record を読む。失敗時は空 dict。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        return {}
    try:
        w3 = _w3()
        ur = w3.eth.contract(address=Web3.to_checksum_address(s.ens_universal_resolver), abi=UNIVERSAL_RESOLVER_ABI)
        resolver_addr, _, _ = ur.functions.findResolver(dns_encode(name)).call()
        if int(resolver_addr, 16) == 0:
            return {}
        r = w3.eth.contract(address=resolver_addr, abi=RESOLVER_ABI)
        node = namehash(name)
        out = {}
        for k in keys or PROFILE_KEYS:
            v = r.functions.text(node, k).call()
            if v:
                out[k] = v
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
    """会社管理者のウォレットで送る tx（register + record 書き込み）の calldata。
    会社名のサブレジストリとリゾルバは ENS から解決する。"""
    s = get_settings()
    if not s.sepolia_rpc_url:
        raise RuntimeError("RPC 未設定のため calldata を生成できません")
    w3 = _w3()
    reg = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=ETH_REGISTRY_ABI)
    parent_label = company_name.removesuffix(".eth")
    sub = reg.functions.getSubregistry(parent_label).call()
    if int(sub, 16) == 0:
        raise RuntimeError(f"{company_name} にサブレジストリがありません。`ens subregistry deploy {company_name} --chain sepolia` で作成してください")
    ur = w3.eth.contract(address=Web3.to_checksum_address(s.ens_universal_resolver), abi=UNIVERSAL_RESOLVER_ABI)
    resolver_addr, _, _ = ur.functions.findResolver(dns_encode(company_name)).call()
    if int(resolver_addr, 16) == 0:
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
