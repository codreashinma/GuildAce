"""Sepolia の Escrow との連携（web3.py）。
- 入金 / 支払い tx のレシート検証（イベントを読む）
- Jury 結果の resolve 送信（サーバー署名者 = arbiter）
チェーン未設定時はモック。"""

import secrets

from eth_utils import keccak
from web3 import Web3

from ..config import get_settings

ESCROW_ABI = [
    {"type": "function", "name": "deposit", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "release", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "recipients", "type": "address[]"}, {"name": "amounts", "type": "uint256[]"}], "outputs": []},
    {"type": "function", "name": "resolve", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "recipients", "type": "address[]"}, {"name": "amounts", "type": "uint256[]"}], "outputs": []},
    {"type": "function", "name": "getCase", "stateMutability": "view", "inputs": [{"name": "caseId", "type": "bytes32"}],
     "outputs": [{"name": "", "type": "tuple", "components": [
         {"name": "client", "type": "address"}, {"name": "token", "type": "address"}, {"name": "amount", "type": "uint256"}, {"name": "status", "type": "uint8"}]}]},
    {"type": "event", "name": "Deposited", "anonymous": False, "inputs": [
        {"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "client", "type": "address", "indexed": True},
        {"name": "token", "type": "address", "indexed": False}, {"name": "amount", "type": "uint256", "indexed": False}]},
    {"type": "event", "name": "Released", "anonymous": False, "inputs": [
        {"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "recipients", "type": "address[]", "indexed": False}, {"name": "amounts", "type": "uint256[]", "indexed": False}]},
    {"type": "event", "name": "Resolved", "anonymous": False, "inputs": [
        {"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "recipients", "type": "address[]", "indexed": False}, {"name": "amounts", "type": "uint256[]", "indexed": False}]},
]


def escrow_case_id(case_id: str) -> str:
    return "0x" + keccak(text=case_id).hex()


def _w3() -> Web3:
    s = get_settings()
    return Web3(Web3.HTTPProvider(s.sepolia_rpc_url))


def _escrow(w3: Web3):
    s = get_settings()
    return w3.eth.contract(address=Web3.to_checksum_address(s.escrow_address), abi=ESCROW_ABI)


def server_address() -> str | None:
    s = get_settings()
    if not s.server_private_key:
        return None
    from eth_account import Account

    return Account.from_key(s.server_private_key).address


def verify_event(tx_hash: str, event_name: str, case_id_hex: str, *, client: str | None = None, amount: int | None = None) -> None:
    """tx のレシートに期待するイベントがあるか確認する。無ければ ValueError。"""
    s = get_settings()
    if not s.chain_enabled:
        return  # モック
    w3 = _w3()
    receipt = w3.eth.get_transaction_receipt(tx_hash)
    if receipt is None or receipt["status"] != 1:
        raise ValueError("トランザクションが成功していません")
    if receipt["to"] and receipt["to"].lower() != s.escrow_address.lower():
        raise ValueError("Escrow 宛のトランザクションではありません")
    event = getattr(_escrow(w3).events, event_name)()
    logs = event.process_receipt(receipt)
    for log in logs:
        args = log["args"]
        if "0x" + args["caseId"].hex() != case_id_hex.lower():
            continue
        if client and args.get("client", "").lower() != client.lower():
            raise ValueError("入金者が発注者と一致しません")
        if amount is not None and int(args.get("amount", 0)) != amount:
            raise ValueError("入金額が予算と一致しません")
        return
    raise ValueError(f"{event_name} イベントが見つかりません")


def send_resolve(case_id_hex: str, recipients: list[str], amounts: list[int]) -> str:
    s = get_settings()
    if not s.chain_enabled or not s.server_private_key:
        return "0xmock" + secrets.token_hex(29)
    w3 = _w3()
    from eth_account import Account

    acct = Account.from_key(s.server_private_key)
    fn = _escrow(w3).functions.resolve(
        bytes.fromhex(case_id_hex[2:]), [Web3.to_checksum_address(r) for r in recipients], amounts
    )
    tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address), "chainId": s.chain_id})
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    w3.eth.wait_for_transaction_receipt(h, timeout=180)
    return h.to_0x_hex()
