"""Escrow コントラクト（タスク単位）との連携。ABI・ID 導出・読み取り・tx 組み立て。
tx の送信はチェーン連携ワーカー（services/worker.py）だけが行う（ADR-006）。"""

import secrets
from typing import Any

from eth_utils import keccak
from web3 import Web3

from ..config import get_settings

ESCROW_ABI: list[dict[str, Any]] = [
    {"type": "function", "name": "openCase", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "token", "type": "address"}, {"name": "approvers", "type": "address[]"}, {"name": "threshold", "type": "uint8"}], "outputs": []},
    {"type": "function", "name": "fundTask", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}, {"name": "amount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "submit", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}, {"name": "deliverableHash", "type": "bytes32"}, {"name": "payee", "type": "address"}], "outputs": []},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}, {"name": "deliverableHash", "type": "bytes32"}, {"name": "payee", "type": "address"}, {"name": "approver", "type": "address"}, {"name": "signature", "type": "bytes"}], "outputs": []},
    {"type": "function", "name": "dispute", "stateMutability": "nonpayable", "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}], "outputs": []},
    {"type": "function", "name": "resolve", "stateMutability": "nonpayable",
     "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}, {"name": "payAmount", "type": "uint256"}, {"name": "refundAmount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "getCase", "stateMutability": "view", "inputs": [{"name": "caseId", "type": "bytes32"}],
     "outputs": [{"type": "tuple", "components": [{"name": "client", "type": "address"}, {"name": "token", "type": "address"}, {"name": "approvers", "type": "address[]"}, {"name": "threshold", "type": "uint8"}]}]},
    {"type": "function", "name": "getTask", "stateMutability": "view", "inputs": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}],
     "outputs": [{"type": "tuple", "components": [{"name": "amount", "type": "uint256"}, {"name": "payee", "type": "address"}, {"name": "deliverableHash", "type": "bytes32"}, {"name": "approvalCount", "type": "uint8"}, {"name": "status", "type": "uint8"}]}]},
    {"type": "event", "name": "CaseOpened", "anonymous": False, "inputs": [
        {"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "client", "type": "address", "indexed": True},
        {"name": "token", "type": "address", "indexed": False}, {"name": "approvers", "type": "address[]", "indexed": False}, {"name": "threshold", "type": "uint8", "indexed": False}]},
    {"type": "event", "name": "TaskFunded", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}, {"name": "amount", "type": "uint256", "indexed": False}]},
    {"type": "event", "name": "Submitted", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}, {"name": "deliverableHash", "type": "bytes32", "indexed": False}, {"name": "payee", "type": "address", "indexed": False}]},
    {"type": "event", "name": "Approved", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}, {"name": "approver", "type": "address", "indexed": True}, {"name": "deliverableHash", "type": "bytes32", "indexed": False}, {"name": "approvalCount", "type": "uint8", "indexed": False}]},
    {"type": "event", "name": "Paid", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}, {"name": "payee", "type": "address", "indexed": True}, {"name": "amount", "type": "uint256", "indexed": False}]},
    {"type": "event", "name": "Disputed", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}]},
    {"type": "event", "name": "Resolved", "anonymous": False, "inputs": [{"name": "caseId", "type": "bytes32", "indexed": True}, {"name": "taskId", "type": "bytes32", "indexed": True}, {"name": "paid", "type": "uint256", "indexed": False}, {"name": "refunded", "type": "uint256", "indexed": False}]},
]

TASK_STATUS = {0: "none", 1: "funded", 2: "submitted", 3: "paid", 4: "disputed", 5: "resolved"}


def escrow_case_id(case_id: str) -> str:
    return "0x" + keccak(text=case_id).hex()


def escrow_task_id(task_id: str) -> str:
    return "0x" + keccak(text=task_id).hex()


def deliverable_hash(text: str) -> str:
    """成果物のハッシュ（ADR-005: 実体はオフチェーン、ハッシュだけをオンチェーンへ）"""
    return "0x" + keccak(text=text or "").hex()


def w3() -> Web3:
    return Web3(Web3.HTTPProvider(get_settings().sepolia_rpc_url, request_kwargs={"timeout": 60}))


def escrow(w: Web3):
    return w.eth.contract(address=Web3.to_checksum_address(get_settings().escrow_address), abi=ESCROW_ABI)


def server_address() -> str | None:
    s = get_settings()
    if not s.server_private_key:
        return None
    from eth_account import Account

    return Account.from_key(s.server_private_key).address


def approval_typed_data(case_id_hex: str, task_id_hex: str, deliverable_hash_hex: str, payee: str) -> dict:
    """承認者が署名する EIP-712 typed data（フロントの signTypedData と、コントラクトの _hashTypedDataV4 に一致させる）"""
    s = get_settings()
    return {
        "types": {
            "EIP712Domain": [{"name": "name", "type": "string"}, {"name": "version", "type": "string"}, {"name": "chainId", "type": "uint256"}, {"name": "verifyingContract", "type": "address"}],
            "Approval": [{"name": "caseId", "type": "bytes32"}, {"name": "taskId", "type": "bytes32"}, {"name": "deliverableHash", "type": "bytes32"}, {"name": "payee", "type": "address"}],
        },
        "primaryType": "Approval",
        "domain": {"name": "ChoiceEscrow", "version": "1", "chainId": s.chain_id, "verifyingContract": s.escrow_address or "0x" + "00" * 20},
        "message": {"caseId": case_id_hex, "taskId": task_id_hex, "deliverableHash": deliverable_hash_hex, "payee": Web3.to_checksum_address(payee)},
    }


def recover_approval_signer(typed: dict, signature: str) -> str:
    from eth_account import Account
    from eth_account.messages import encode_typed_data

    return Account.recover_message(encode_typed_data(full_message=typed), signature=signature)


def verify_case_opened(tx_hash: str, case_id_hex: str, client: str, approvers: list[str], threshold: int) -> None:
    """発注者が送った openCase の tx を検証する（モック時は何もしない）"""
    s = get_settings()
    if not s.chain_enabled:
        return
    if tx_hash.startswith("0xmock"):
        raise ValueError("Mock tx hashes are not accepted in this environment (chain configured). Send openCase from your Wallet")
    w = w3()
    receipt = w.eth.get_transaction_receipt(tx_hash)
    if receipt is None or receipt["status"] != 1:
        raise ValueError("The transaction did not succeed")
    for log in escrow(w).events.CaseOpened().process_receipt(receipt):
        a = log["args"]
        if "0x" + a["caseId"].hex() != case_id_hex.lower():
            continue
        if a["client"].lower() != client.lower():
            raise ValueError("The address that opened the Case does not match the Client")
        if [x.lower() for x in a["approvers"]] != [x.lower() for x in approvers] or int(a["threshold"]) != threshold:
            raise ValueError("The Approver settings do not match")
        return
    raise ValueError("CaseOpened event not found")


def read_task(case_id_hex: str, task_id_hex: str) -> dict | None:
    """オンチェーンの正本を読む（投影の再同期用）。モック時は None。"""
    s = get_settings()
    if not s.chain_enabled:
        return None
    t = escrow(w3()).functions.getTask(bytes.fromhex(case_id_hex[2:]), bytes.fromhex(task_id_hex[2:])).call()
    return {"amount": int(t[0]), "payee": t[1], "deliverable_hash": "0x" + t[2].hex(), "approval_count": int(t[3]), "status": TASK_STATUS.get(int(t[4]), "none")}


def mock_tx_hash() -> str:
    return "0xmock" + secrets.token_hex(29)
