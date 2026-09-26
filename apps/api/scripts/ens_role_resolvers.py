"""役割ごとの PermissionedResolver をデプロイする（1 回だけ・冪等）。
- reputation resolver: admin = Reputation 鍵。reputation.<agent> subname のレコード置き場
- project resolver:    admin = Project 鍵。project-*.<agent> subname のレコード置き場
デプロイは運用ウォレット（ops）が送る。出力を .env の ENS_REPUTATION_RESOLVER / ENS_PROJECT_RESOLVER に設定する。"""

import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from eth_abi import encode  # noqa: E402
from eth_utils import keccak  # noqa: E402
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import ens  # noqa: E402

FACTORY_ABI = [{"type": "function", "name": "deployProxy", "stateMutability": "nonpayable",
                "inputs": [{"name": "implementation", "type": "address"}, {"name": "salt", "type": "uint256"}, {"name": "data", "type": "bytes"}], "outputs": [{"type": "address"}]}]
INIT_ABI = [{"type": "function", "name": "initialize", "stateMutability": "nonpayable",
             "inputs": [{"name": "admin", "type": "address"}, {"name": "roleBitmap", "type": "uint256"}, {"name": "setters", "type": "bytes[]"}], "outputs": []}]


def main() -> None:
    s = get_settings()
    w3 = ens._w3()
    ops = ens._account().address
    factory = w3.eth.contract(address=Web3.to_checksum_address(s.ensv2_verifiable_factory), abi=FACTORY_ABI)
    out = {}
    for role in ("reputation", "project"):
        admin = ens._account(role).address
        if admin.lower() == ops.lower():
            print(f"{role}: skipped because the role key is not configured"); continue
        salt = int.from_bytes(keccak(encode(["bytes32", "address", "uint256"], [keccak(text="OwnedResolver"), admin, 0])), "big")
        init = w3.eth.contract(abi=INIT_ABI).encode_abi("initialize", args=[admin, ens.ALL_ROLES, []])
        fn = factory.functions.deployProxy(Web3.to_checksum_address(s.ensv2_resolver_impl), salt, bytes.fromhex(init[2:]))
        addr = fn.call({"from": ops})
        if w3.eth.get_code(addr) in (b"", b"\x00"):
            print(f"Deployed {role} resolver: {addr}")
            print("  tx", ens._send(w3, fn))
        else:
            print(f"{role} resolver already exists: {addr}")
        eac = w3.eth.contract(address=addr, abi=ens.EAC_ABI)
        print(f"  admin({admin}) root SET_TEXT:", eac.functions.hasRootRoles(ens.RESOLVER_ROLE_SET_TEXT, admin).call(),
              "/ ops root SET_TEXT:", eac.functions.hasRootRoles(ens.RESOLVER_ROLE_SET_TEXT, ops).call())
        out[role] = addr
    print("\nSet these in .env:")
    if "reputation" in out: print(f"ENS_REPUTATION_RESOLVER={out['reputation']}")
    if "project" in out: print(f"ENS_PROJECT_RESOLVER={out['project']}")


if __name__ == "__main__":
    main()
