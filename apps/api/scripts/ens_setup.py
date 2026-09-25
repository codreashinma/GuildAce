"""ENSv2（Sepolia beta）の初期セットアップ。サーバー署名者で 1 回だけ実行する。

やること:
  1. サーバー署名者用の OwnedResolver を VerifiableFactory でデプロイ（既にあればスキップ）
  2. 親名（既定 choice.eth）を ETHRegistrar で commit/reveal 登録（既に登録済みならスキップ。登録料は ENS のテスト用 USDC。mint は誰でも可）
  3. 親名用の UserRegistry（サブレジストリ）をデプロイし、親名に設定（既にあればスキップ）
最後に .env に書く ENS_OWNED_RESOLVER / ENS_PARENT_SUBREGISTRY を出力する。

使い方: SEPOLIA_RPC_URL / SERVER_PRIVATE_KEY を .env に設定して
  .venv/bin/python scripts/ens_setup.py            # 実行（Sepolia ETH が必要）
  .venv/bin/python scripts/ens_setup.py --dry-run  # 送信せずに手順・料金・予定アドレスだけ表示
契約アドレスは ensdomains/ens-cli（2026-07-30 のデプロイ）に合わせている。変わっていたら .env の ENSV2_* で上書きする。"""

import os
import secrets
import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from eth_abi import encode  # noqa: E402
from eth_account import Account  # noqa: E402
from eth_utils import keccak  # noqa: E402
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services.ens import ALL_ROLES, V2_REGISTRY_ABI, namehash  # noqa: E402

ZERO = "0x" + "00" * 20
FACTORY_ABI = [{"type": "function", "name": "deployProxy", "stateMutability": "nonpayable",
                "inputs": [{"name": "implementation", "type": "address"}, {"name": "salt", "type": "uint256"}, {"name": "data", "type": "bytes"}],
                "outputs": [{"type": "address"}]}]
RESOLVER_INIT_ABI = [{"type": "function", "name": "initialize", "stateMutability": "nonpayable",
                      "inputs": [{"name": "admin", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "setters", "type": "bytes[]"}], "outputs": []}]
USER_REGISTRY_INIT_ABI = [{"type": "function", "name": "initialize", "stateMutability": "nonpayable",
                           "inputs": [{"name": "rootAccount", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}], "outputs": []}]
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
ERC20_ABI = [
    {"type": "function", "name": "mint", "stateMutability": "nonpayable", "inputs": [{"name": "to", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": []},
    {"type": "function", "name": "approve", "stateMutability": "nonpayable", "inputs": [{"name": "spender", "type": "address"}, {"name": "amount", "type": "uint256"}], "outputs": [{"type": "bool"}]},
    {"type": "function", "name": "balanceOf", "stateMutability": "view", "inputs": [{"name": "a", "type": "address"}], "outputs": [{"type": "uint256"}]},
]
DURATION = 365 * 24 * 3600


DRY = "--dry-run" in sys.argv


def main() -> None:
    s = get_settings()
    if not (s.sepolia_rpc_url and s.server_private_key):
        sys.exit("SEPOLIA_RPC_URL と SERVER_PRIVATE_KEY を .env に設定してください")
    w3 = Web3(Web3.HTTPProvider(s.sepolia_rpc_url))
    acct = Account.from_key(s.server_private_key)
    me = acct.address
    bal = w3.eth.get_balance(me)
    print("signer:", me, "balance:", w3.from_wei(bal, "ether"), "ETH", "(dry-run)" if DRY else "")
    if not DRY and bal < w3.to_wei(0.01, "ether"):
        sys.exit(f"Sepolia ETH が不足しています。{me} に 0.05 ETH ほど送ってください（faucet: https://cloud.google.com/application/web3/faucet/ethereum/sepolia など）")

    def send(fn) -> str:
        if DRY:
            print("  [dry-run] 送信予定:", fn.fn_name, "→", fn.address)
            return "0x" + "00" * 32
        tx = fn.build_transaction({"from": me, "nonce": w3.eth.get_transaction_count(me), "chainId": s.chain_id})
        h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
        r = w3.eth.wait_for_transaction_receipt(h, timeout=240)
        if r["status"] != 1:
            sys.exit(f"tx failed: {h.to_0x_hex()}")
        print("  tx", h.to_0x_hex())
        return h.to_0x_hex()

    factory = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_verifiable_factory), abi=FACTORY_ABI)
    eth_registry = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_eth_registry), abi=V2_REGISTRY_ABI)
    registrar = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_registrar), abi=REGISTRAR_ABI)
    label = s.ens_parent_name.removesuffix(".eth")

    # 1. OwnedResolver
    resolver_addr = s.ens_owned_resolver
    if not resolver_addr:
        salt = int.from_bytes(keccak(encode(["bytes32", "address", "uint256"], [keccak(text="OwnedResolver"), me, 0])), "big")
        init = w3.eth.contract(abi=RESOLVER_INIT_ABI).encode_abi("initialize", args=[me, ALL_ROLES, []])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_resolver_impl), salt, bytes.fromhex(init[2:]))
        resolver_addr = fn.call({"from": me})
        if w3.eth.get_code(resolver_addr) in (b"", b"\x00"):
            print("1. OwnedResolver をデプロイ:", resolver_addr)
            send(fn)
        else:
            print("1. OwnedResolver は既にあります:", resolver_addr)
    else:
        print("1. OwnedResolver（.env）:", resolver_addr)

    # 2. 親名の登録
    state = eth_registry.functions.getState(int.from_bytes(keccak(text=label), "big")).call()
    status, _, owner, token_id, _ = state
    if status == 2:
        print(f"2. {s.ens_parent_name} は登録済み（owner={owner}）")
        if owner.lower() != me.lower():
            sys.exit("親名の所有者がサーバー署名者ではありません。別の親名を ENS_PARENT_NAME に設定してください")
    else:
        if not registrar.functions.isAvailable(label).call():
            sys.exit(f"{s.ens_parent_name} は取得できません（他者が予約/登録済み）")
        base, premium = registrar.functions.getRegisterPrice(label, DURATION, Web3.to_checksum_address(s.ensv2_payment_token)).call()
        total = base + premium
        token = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_payment_token), abi=ERC20_ABI)
        print(f"2. {s.ens_parent_name} を登録します。料金 {total} (payment token 最小単位)")
        if token.functions.balanceOf(me).call() < total:
            print("  テスト用トークンを mint")
            send(token.functions.mint(me, total))
        send(token.functions.approve(registrar.address, total))
        secret = bytes.fromhex(os.environ.get("ENS_COMMIT_SECRET", secrets.token_hex(32)).removeprefix("0x"))
        commitment = registrar.functions.makeCommitment(label, me, secret, ZERO, Web3.to_checksum_address(resolver_addr), DURATION, b"\x00" * 32).call()
        print("  commit")
        send(registrar.functions.commit(commitment))
        print("  60 秒待機（minCommitmentAge）")
        if not DRY:
            time.sleep(75)
        print("  register")
        send(registrar.functions.register(label, me, secret, ZERO, Web3.to_checksum_address(resolver_addr), DURATION, Web3.to_checksum_address(s.ensv2_payment_token), b"\x00" * 32))
        if not DRY:
            _, _, _, token_id, _ = eth_registry.functions.getState(int.from_bytes(keccak(text=label), "big")).call()

    # 3. サブレジストリ
    sub = eth_registry.functions.getSubregistry(label).call()
    if int(sub, 16) != 0:
        print("3. サブレジストリは設定済み:", sub)
    else:
        salt = int.from_bytes(keccak(encode(["bytes32", "bytes32", "uint256"], [keccak(text="UserRegistry"), namehash(s.ens_parent_name), 0])), "big")
        init = w3.eth.contract(abi=USER_REGISTRY_INIT_ABI).encode_abi("initialize", args=[me, ALL_ROLES])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_subregistry_impl), salt, bytes.fromhex(init[2:]))
        sub = fn.call({"from": me})
        if w3.eth.get_code(sub) in (b"", b"\x00"):
            print("3. UserRegistry をデプロイ:", sub)
            send(fn)
        print("   親名にサブレジストリを設定")
        if DRY and status != 2:
            print("  [dry-run] 送信予定: setSubregistry（tokenId は登録後に確定）")
        else:
            send(eth_registry.functions.setSubregistry(token_id, sub))

    # 4. 役割ごとのリゾルバ（Reputation / Project）は scripts/ens_role_resolvers.py で用意する
    print("4. 役割リゾルバ: scripts/ens_role_resolvers.py を実行し、ENS_REPUTATION_RESOLVER / ENS_PROJECT_RESOLVER を .env に設定してください")

    print("\n.env に追記してください:")
    print(f"ENS_OWNED_RESOLVER={resolver_addr}")
    print(f"ENS_PARENT_SUBREGISTRY={sub}")
    print("ENS_WRITE_ENABLED=true")


if __name__ == "__main__":
    main()
