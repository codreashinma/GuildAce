"""ENSv2（Sepolia）の名前を手動確認する読み取り専用ツール。

使い方:
  .venv/bin/python scripts/ens_check.py                    # 親名 + DB にある Agent / 人員の名前をまとめて確認
  .venv/bin/python scripts/ens_check.py web-pm.choice.eth  # 任意の名前を確認
鍵は不要。SEPOLIA_RPC_URL が無ければ公開 RPC を使う。"""

import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from eth_utils import keccak  # noqa: E402
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.ens import PERSON_KEYS, PROFILE_KEYS, PROJECT_KEYS, RESOLVER_ABI, V2_REGISTRY_ABI, namehash, resolve_v2  # noqa: E402

PUBLIC_RPC = "https://ethereum-sepolia-rpc.publicnode.com"


def show(w3: Web3, name: str) -> None:
    s = get_settings()
    print(f"\n=== {name}")
    labels = name.split(".")
    eth_reg = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=V2_REGISTRY_ABI)
    st = eth_reg.functions.getState(int.from_bytes(keccak(text=labels[-2]), "big")).call()
    status = {0: "未登録（取得可能）", 1: "予約済み", 2: "登録済み"}.get(st[0], st[0])
    print(f"  {labels[-2]}.eth: {status}  owner={st[2]}  subregistry={eth_reg.functions.getSubregistry(labels[-2]).call()}")
    print(f"    https://sepolia.etherscan.io/address/{s.ensv2_eth_registry}#readContract  (getState({int.from_bytes(keccak(text=labels[-2]), 'big')}))")
    resolver, registry, label = resolve_v2(w3, name)
    if resolver is None:
        print("  resolver: なし（名前が未発行、または親のサブレジストリ未設定）")
        return
    print(f"  registry: {registry}  label: {label}")
    print(f"  resolver: {resolver}  https://sepolia.etherscan.io/address/{resolver}#readContract")
    if registry:
        reg = w3.eth.contract(address=registry, abi=V2_REGISTRY_ABI)
        st = reg.functions.getState(int.from_bytes(keccak(text=label), "big")).call()
        print(f"  state: status={st[0]} expiry={st[1]} owner={st[2]}")
    r = w3.eth.contract(address=resolver, abi=RESOLVER_ABI)
    node = namehash(name)
    print(f"  namehash: 0x{node.hex()}")
    print(f"  addr: {r.functions.addr(node).call()}")
    for k in PROFILE_KEYS + PROJECT_KEYS + PERSON_KEYS:
        v = r.functions.text(node, k).call()
        if v:
            print(f"  text[{k}] = {v}")


def main() -> None:
    s = get_settings()
    w3 = Web3(Web3.HTTPProvider(s.sepolia_rpc_url or PUBLIC_RPC, request_kwargs={"timeout": 30}))
    print("rpc:", s.sepolia_rpc_url or PUBLIC_RPC, "block:", w3.eth.block_number)
    if len(sys.argv) > 1:
        for n in sys.argv[1:]:
            show(w3, n)
        return
    show(w3, s.ens_parent_name)
    try:
        from app.db import SessionLocal
        from app.models import Agent, Member

        db = SessionLocal()
        for a in db.query(Agent).filter(Agent.ens_name.isnot(None)):
            show(w3, a.ens_name)
        for m in db.query(Member).filter(Member.ens_status == "written"):
            show(w3, m.ens_name)
    except Exception as e:  # noqa: BLE001
        print("(DB に接続できないため DB 上の名前は省略:", str(e)[:60], ")")


if __name__ == "__main__":
    main()
