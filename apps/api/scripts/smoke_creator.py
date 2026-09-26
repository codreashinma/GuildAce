"""Sepolia 実機で「Creator 所有の Agent」を通しで確認する。
一時鍵で .eth を登録 → /ens/setup-calldata でリゾルバとサブレジストリを用意 → creator モードで Agent を公開（名前空間の tx に署名）
→ 権限表（EAC）・reputation subname・専門 Agent を確認 → 案件を開いて project subname が Project 鍵で発行されることを確認。
運用ウォレット（ops）から一時鍵へ少額の Sepolia ETH を送る。

使い方: API（chain 有効・ENS_WRITE_ENABLED=true）を起動して
  .venv/bin/python scripts/smoke_creator.py [http://localhost:8001] [--skip-case]"""

import secrets
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
sys.path.insert(0, __file__.rsplit("/", 2)[0])
from _client import Client  # noqa: E402
from eth_account import Account  # noqa: E402
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import ens  # noqa: E402
from app.services.chain import ESCROW_ABI  # noqa: E402
from ens_setup import DURATION, ERC20_ABI, REGISTRAR_ABI, ZERO  # noqa: E402

BASE = next((a for a in sys.argv[1:] if a.startswith("http")), "http://localhost:8001")
SKIP_CASE = "--skip-case" in sys.argv
AGENT_ID = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--agent=")), None)  # 公開済み Agent から案件のステップだけを再実行


def send(w3, acct, fn=None, *, to=None, data=None, label=""):
    if fn is not None:
        tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"), "chainId": 11155111})
    else:
        tx = {"to": Web3.to_checksum_address(to), "data": data, "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"), "chainId": 11155111}
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.2)
        tx["maxFeePerGas"] = w3.eth.gas_price * 2
        tx["maxPriorityFeePerGas"] = w3.to_wei(1, "gwei")
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=240)
    assert r["status"] == 1, f"tx failed {h.to_0x_hex()} ({label})"
    print(f"  tx {h.to_0x_hex()}  {label}")
    return h.to_0x_hex()


def main() -> None:
    s = get_settings()
    assert s.chain_enabled and s.ens_write_enabled, "chain / ENS 書き込みが有効ではありません"
    w3 = Web3(Web3.HTTPProvider(s.sepolia_rpc_url, request_kwargs={"timeout": 60}))
    ops = Account.from_key(s.server_private_key)
    creator = Client(BASE)
    creator.login()
    acct = creator.acct
    if AGENT_ID:
        a = creator.get(f"/agents/{AGENT_ID}")
        agent = a
        print("resume with agent:", a["ens_name"])
        return run_case(w3, s, ops, agent, a)
    print("creator (temp):", acct.address)

    # 0. ガス代
    need = w3.to_wei(0.03, "ether")
    if w3.eth.get_balance(acct.address) < need:
        tx = {"to": acct.address, "value": need, "nonce": w3.eth.get_transaction_count(ops.address, "pending"), "chainId": 11155111, "gas": 21000, "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(1, "gwei")}
        h = w3.eth.send_raw_transaction(ops.sign_transaction(tx).raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=240)
        print("  funded creator with 0.03 ETH")

    # 1. Creator の .eth を登録（テスト用トークンで支払い）
    label = "codrea-cr-" + secrets.token_hex(3)
    name = f"{label}.eth"
    registrar = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_registrar), abi=REGISTRAR_ABI)
    token = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_payment_token), abi=ERC20_ABI)
    base, premium = registrar.functions.getRegisterPrice(label, DURATION, token.address).call()
    total = base + premium
    print(f"1. {name} を登録（料金 {total}）")
    send(w3, acct, token.functions.mint(acct.address, total), label="mint")
    send(w3, acct, token.functions.approve(registrar.address, total), label="approve")
    secret = secrets.token_bytes(32)
    commitment = registrar.functions.makeCommitment(label, acct.address, secret, ZERO, ZERO, DURATION, b"\x00" * 32).call()
    send(w3, acct, registrar.functions.commit(commitment), label="commit")
    print("  75 秒待機（minCommitmentAge）")
    time.sleep(75)
    send(w3, acct, registrar.functions.register(label, acct.address, secret, ZERO, ZERO, DURATION, token.address, b"\x00" * 32), label="register")
    co = creator.get(f"/ens/check-owner?name={name}")
    assert co["is_mine"], co
    print("   check-owner: is_mine =", co["is_mine"])

    # 2. リゾルバとサブレジストリを Creator 自身で用意（/ens/setup-calldata）
    rd = creator.get(f"/ens/readiness?name={name}")
    assert not rd["ready"] and set(rd["missing"]) == {"subregistry", "resolver"}, rd
    sc = creator.get(f"/ens/setup-calldata?name={name}")
    print(f"2. setup-calldata: {len(sc['txs'])} txs（resolver → {sc['resolver']['address'][:10]}…, subregistry → {sc['subregistry']['address'][:10]}…）")
    for t in sc["txs"]:
        send(w3, acct, to=t["to"], data=t["data"], label=t["label"][:50])
    rd = creator.get(f"/ens/readiness?name={name}")
    assert rd["ready"], rd
    print("   readiness: ready =", rd["ready"])

    # 3. creator モードで Agent を公開（名前空間の tx に署名）
    agent = creator.post("/agents", {"name": "Creator 所有 PM Agent", "label": "web-pm-cr-" + secrets.token_hex(2), "description": "Creator 自身の名前空間に置いた PM Agent", "category": "web",
                                     "rules": "案件を 4〜6 タスクに分解する", "fee_bps": 200, "parent_ens_name": name}, expect=201)
    r = creator.post(f"/agents/{agent['id']}/publish")
    assert r["mode"] == "creator" and not r["mock"], r
    print(f"3. publish: {len(r['txs'])} txs、subregistry → {r['subregistry'][:10]}…、{r['reputation_name']}")
    last = None
    for t in r["txs"]:
        last = send(w3, acct, to=t["to"], data=t["data"], label=t["label"][:60])
    a = creator.post(f"/agents/{agent['id']}/ens-written", {"tx_hash": last})
    assert a["status"] == "published" and a["ens_subregistry"] and not a["ens_error"], a
    print("   published:", a["ens_name"], "subregistry", a["ens_subregistry"][:10], "error:", a["ens_error"])

    # 4. 権限表・record を確認（Reputation 鍵の初期書き込みは worker が行うので少し待つ）
    time.sleep(20)
    d = creator.get(f"/agents/{agent['id']}")
    print("4. ens_records:", {k: v[:24] for k, v in d["ens_records"].items()})
    print("   reputation:", d["ens_reputation_name"], d["ens_reputation_records"])
    print("   subagents:", list(d["ens_subagents"]))
    for role in d["ens_roles"]:
        print(f"   role {role['role'][:12]:12} account {role['account'][:10]}… verified={role.get('verified')}")
    assert all(role.get("verified") for role in d["ens_roles"]), "役割分離が設計どおりではありません"
    assert len(d["ens_subagents"]) == 4 and d["ens_records"].get("codrea.agent.category") == "web"
    rs = creator.get(f"/ens/resolve?name={a['ens_name']}")
    assert rs["owner"].lower() == acct.address.lower() and rs["wildcard"]["matches"], rs
    print("   /ens/resolve: owner = creator, ENSIP-10 matches =", rs["wildcard"]["matches"])

    if SKIP_CASE:
        print("\nCREATOR SMOKE PASSED (case skipped)")
        return
    run_case(w3, s, ops, agent, a)


def run_case(w3, s, ops, agent, a):
    # 5. 案件を開いて project subname（Project 鍵が Creator のサブレジストリに発行）
    client = Client(BASE)
    client.login()
    if w3.eth.get_balance(client.address) < w3.to_wei(0.004, "ether"):
        tx = {"to": client.address, "value": w3.to_wei(0.006, "ether"), "nonce": w3.eth.get_transaction_count(ops.address, "pending"), "chainId": 11155111, "gas": 21000, "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(1, "gwei")}
        h = w3.eth.send_raw_transaction(ops.sign_transaction(tx).raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=240)
    case = client.post("/cases", {"agent_id": agent["id"], "title": "Creator Agent の実機案件", "description": "小さな LP", "budget_usdc": 6, "idkit_response": None}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval"}, timeout=180)
    usdc = w3.eth.contract(address=Web3.to_checksum_address(s.usdc_address), abi=ERC20_ABI)
    escrow = w3.eth.contract(address=Web3.to_checksum_address(s.escrow_address), abi=ESCROW_ABI)
    budget = int(case["budget"])
    print("5. openCase")
    send(w3, client.acct, usdc.functions.mint(client.address, budget), label="mint USDC")
    send(w3, client.acct, usdc.functions.approve(escrow.address, budget), label="approve USDC")
    h = send(w3, client.acct, escrow.functions.openCase(bytes.fromhex(case["escrow_case_id"][2:]), usdc.address, [Web3.to_checksum_address(x) for x in case["approvers"]], case["threshold"]), label="openCase")
    client.post(f"/cases/{case['id']}/opened", {"tx_hash": h})
    t0 = time.time()
    while time.time() - t0 < 300:
        c = client.get(f"/cases/{case['id']}")
        if c.get("project_ens_name") and c.get("project_ens_tx_hash") and not c["project_ens_tx_hash"].startswith("0xmock"):
            break
        time.sleep(3)
    else:
        raise TimeoutError("project subname が発行されませんでした")
    pr = client.get(f"/ens/resolve?name={c['project_ens_name']}")
    print("   project subname:", c["project_ens_name"], "owner", pr["owner"][:10], "title =", pr["texts"].get("codrea.project.title"))
    assert pr["owner"].lower() == ens._account("project").address.lower(), pr
    assert pr["texts"].get("codrea.project.case") == case["id"]
    print("\nCREATOR SMOKE PASSED")
    print(f"agent: {a['ens_name']}  ({BASE.replace('8003', '3000')}/agents/{agent['id']})")


if __name__ == "__main__":
    main()
