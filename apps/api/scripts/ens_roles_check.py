"""EAC の役割分離を実機で検証する（読み取り + eth_call による書き込みシミュレーション。tx は送らない）。
使い方: .venv/bin/python scripts/ens_roles_check.py <agent label>   例: web-pm"""

import sys
import time

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from web3 import Web3  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.services import ens  # noqa: E402

label = sys.argv[1] if len(sys.argv) > 1 else "web-pm"
s = get_settings()
w3 = ens._w3()
name = ens.agent_ens_name(label)
node = ens.namehash(name)
rep_node = ens.namehash(ens.reputation_name(label))
main = ens._resolver(w3)
rep_res = ens._role_resolver(w3, "reputation")
proj_res = ens._role_resolver(w3, "project")
addrs = ens.role_addresses()
print("name:", name)
print("roles:", addrs)


def simulate(role: str, fn, what: str, expect_ok: bool) -> None:
    acct = ens._account(role).address
    try:
        fn.call({"from": acct})
        ok = True
    except Exception:  # noqa: BLE001
        ok = False
    mark = "OK" if ok == expect_ok else "NG"
    print(f"  [{mark}] {role:10} {what:52} -> {'許可' if ok else '拒否'}（期待: {'許可' if expect_ok else '拒否'}）")


print("\n[共有リゾルバ（Owner）]")
simulate("owner", main.functions.setText(node, "description", "x"), "setText(agent, description)", True)
simulate("reputation", main.functions.setText(node, "description", "hacked"), "setText(agent, description)", False)
simulate("reputation", main.functions.setText(node, "codrea.agent.rating", "5.0"), "setText(agent, codrea.agent.rating)", False)
simulate("project", main.functions.setText(node, "codrea.project.status", "x"), "setText(agent, codrea.project.status)", False)
print("[Reputation リゾルバ（reputation.<agent>）]")
simulate("reputation", rep_res.functions.setText(rep_node, "codrea.agent.rating", "4.9"), "setText(reputation.agent, codrea.agent.rating)", True)
simulate("owner", rep_res.functions.setText(rep_node, "codrea.agent.rating", "5.0"), "setText(reputation.agent, codrea.agent.rating)", False)
simulate("project", rep_res.functions.setText(rep_node, "codrea.agent.rating", "5.0"), "setText(reputation.agent, codrea.agent.rating)", False)
print("[Agent サブレジストリ]")
sub = ens._subregistry(w3).functions.getSubregistry(label).call()
print("  subregistry:", sub)
if int(sub, 16):
    reg = w3.eth.contract(address=sub, abi=ens.V2_REGISTRY_ABI)
    args = ("project-test", addrs["project"], "0x" + "00" * 20, proj_res.address, ens.V2_DEFAULT_OWNER_ROLE_BITMAP, int(time.time()) + 3600)
    simulate("project", reg.functions.register(*args), "register(project-test)", True)
    simulate("reputation", reg.functions.register(*args), "register(project-test)", False)
    st = reg.functions.getState(int.from_bytes(ens.keccak(text="reputation"), "big")).call()
    simulate("project", reg.functions.setResolver(st[3], addrs["project"]), "setResolver(reputation subname)", False)
parent = ens._subregistry(w3)
simulate("project", parent.functions.register("hijack", addrs["project"], "0x" + "00" * 20, proj_res.address, ens.V2_DEFAULT_OWNER_ROLE_BITMAP, int(time.time()) + 3600), "register(hijack.guildace.eth)", False)
print("\n[API 用の役割表]")
for r in ens.agent_roles(name, label):
    print(" ", r.get("role"), "verified =", r.get("verified"), r.get("checks", r.get("error")))
