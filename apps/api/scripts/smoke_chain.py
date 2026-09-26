"""Sepolia の本物の Escrow / ENS で 1 案件を通すスモークテスト。
サーバー署名者（ops）から発注者用の一時ウォレットへ少額の ETH を送り、openCase → 工程ごとの預託 → 提出 → 承認（EIP-712）→ 自動支払い までを確認する。
使い方: API（chain 有効）を起動して  .venv/bin/python scripts/smoke_chain.py [http://localhost:8001]"""

import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
sys.path.insert(0, __file__.rsplit("/", 2)[0])
from _client import Client, sign_typed  # noqa: E402
from eth_account import Account  # noqa: E402
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.chain import ESCROW_ABI  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"
ERC20 = [
    {"type": "function", "name": "mint", "stateMutability": "nonpayable", "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
]


def send(w3, acct, fn, value=0):
    tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"), "chainId": 11155111, "value": value})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=240)
    assert r["status"] == 1, f"tx failed {h.to_0x_hex()}"
    print("  tx", h.to_0x_hex())
    return h.to_0x_hex()


def main() -> None:
    s = get_settings()
    assert s.chain_enabled, "Chain is not enabled (SEPOLIA_RPC_URL / ESCROW_ADDRESS / USDC_ADDRESS in .env)"
    w3 = Web3(Web3.HTTPProvider(s.sepolia_rpc_url, request_kwargs={"timeout": 60}))
    ops = Account.from_key(s.server_private_key)
    client = Client(BASE)
    client.login()
    print("client (temp):", client.address)
    # 発注者に少額の ETH を渡す（openCase + approve 用）
    if w3.eth.get_balance(client.address) < w3.to_wei(0.003, "ether"):
        tx = {"to": client.address, "value": w3.to_wei(0.005, "ether"), "nonce": w3.eth.get_transaction_count(ops.address, "pending"), "chainId": 11155111, "gas": 21000, "maxFeePerGas": w3.eth.gas_price * 2, "maxPriorityFeePerGas": w3.to_wei(1, "gwei")}
        h = w3.eth.send_raw_transaction(ops.sign_transaction(tx).raw_transaction)
        w3.eth.wait_for_transaction_receipt(h, timeout=240)
        print("  funded client with 0.005 ETH")

    agents = client.get("/agents")
    agent = next((a for a in agents if a["status"] == "published"), None)
    assert agent, "No published Agent (run the seed)"
    case = client.post("/cases", {"agent_id": agent["id"], "title": "Sepolia live test case", "description": "A small landing page", "budget_usdc": 12, "idkit_response": None}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval"}, timeout=180)
    print("plan:", len(case["tasks"]), "tasks; escrow case", case["escrow_case_id"][:12])

    usdc = w3.eth.contract(address=Web3.to_checksum_address(s.usdc_address), abi=ERC20)
    escrow = w3.eth.contract(address=Web3.to_checksum_address(s.escrow_address), abi=ESCROW_ABI)
    budget = int(case["budget"])
    print("mint + approve USDC")
    send(w3, client.acct, usdc.functions.mint(client.address, budget))
    send(w3, client.acct, usdc.functions.approve(escrow.address, budget))
    print("openCase")
    open_tx = send(w3, client.acct, escrow.functions.openCase(bytes.fromhex(case["escrow_case_id"][2:]), usdc.address, [client.address], 1))
    case = client.post(f"/cases/{case['id']}/opened", {"tx_hash": open_tx})
    print("API accepted openCase; worker funds each task…")
    for _ in range(120):
        case = client.get(f"/cases/{case['id']}")
        if all(t["chain_status"] in ("funded", "submitted", "paid") for t in case["tasks"]):
            break
        time.sleep(3)
    print("funded:", [t["chain_status"] for t in case["tasks"]])
    assert usdc.functions.balanceOf(escrow.address).call() >= budget, "Escrow has not been funded"

    # Human Task があれば発注者以外が受注・提出する
    worker = Client(BASE); worker.login()
    for _ in range(120):
        case = client.get(f"/cases/{case['id']}")
        if all(t["status"] == "done" for t in case["tasks"] if t["type"] == "ai"):
            break
        time.sleep(3)
    for t in case["tasks"]:
        if t["type"] == "human" and t["human_task"] and t["human_task"]["status"] in ("open", "assigned"):
            ht = t["human_task"]
            if ht["status"] == "assigned":
                print("  human task assigned to", ht["assignee"]["ens_name"], "- in live tests, skip declining (which would switch to an open call); handle manually if the assignee cannot accept")
                continue
            worker.post(f"/human-tasks/{ht['id']}/accept", {})
            worker.post(f"/human-tasks/{ht['id']}/submit", {"submission": "https://example.com/photo.jpg"})
    for _ in range(120):
        case = client.get(f"/cases/{case['id']}")
        if all(t["chain_status"] == "submitted" for t in case["tasks"] if t["status"] == "done"):
            break
        time.sleep(3)
    print("submitted on-chain:", [(t["title"][:10], t["chain_status"]) for t in case["tasks"]])

    for t in case["tasks"]:
        if t["chain_status"] != "submitted":
            continue
        typed = client.get(f"/cases/{case['id']}/tasks/{t['id']}/typed-data")
        client.post(f"/cases/{case['id']}/tasks/{t['id']}/approve", {"signature": sign_typed(client, typed), "idkit_response": None})
    print("approvals queued; waiting for on-chain auto-pay…")
    for _ in range(120):
        case = client.get(f"/cases/{case['id']}")
        if all(t["chain_status"] == "paid" for t in case["tasks"] if t["status"] == "done"):
            break
        time.sleep(3)
    print("paid:", [(t["title"][:10], t["chain_status"], t["chain_tx_hash"][:10] if t["chain_tx_hash"] else None) for t in case["tasks"]])
    payee_bal = usdc.functions.balanceOf(Web3.to_checksum_address(agent["payout_address"])).call()
    print("agent payout balance:", payee_bal / 1e6, "USDC; case status:", case["status"], "; project ENS:", case["project_ens_name"])


if __name__ == "__main__":
    main()
