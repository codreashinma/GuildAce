"""モックモードで全フローを通すスモークテスト。
使い方: API を起動した状態で `.venv/bin/python scripts/smoke_flow.py [http://localhost:8001]`"""

import sys
import time

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _client import Client, fake_tx, sign_typed  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"


def main() -> None:
    creator, client, worker, j1, j2, j3 = (Client(BASE) for _ in range(6))
    for c in (creator, client, worker, j1, j2, j3):
        c.login()
    print("V1 login ok:", client.address)

    # --- Agent 作成・公開
    label = "web-pm-" + creator.address[-6:].lower()
    agent = creator.post("/agents", {"name": "Web Dev PM Agent", "label": label, "description": "Builds a web service in 3 days", "category": "web",
                                     "rules": "Break tasks down into small pieces and leave on-site checks to humans", "fee_bps": 200}, expect=201)
    agent = creator.post(f"/agents/{agent['id']}/publish")["agent"]
    agent = creator.wait(f"/agents/{agent['id']}", "status", {"published", "publish_failed"})
    assert agent["status"] == "published", agent
    assert agent["ens_name"] == f"{label}.guildace.eth"
    print("V2 agent published:", agent["ens_name"], agent["ens_tx_hash"][:12])
    # D1: Creator 自身の .eth の下に公開（モックでは所有者チェックと tx を省略）
    own = creator.post("/agents", {"name": "Own-name PM", "label": label, "category": "web", "parent_ens_name": "smokecreator.eth"}, expect=201)  # 同じラベルでも親が違えば OK
    creator.post("/agents", {"name": "dup", "label": label, "category": "web"}, expect=409)  # 同じ親 + 同じラベルは 409
    creator.post("/agents", {"name": "dup", "label": label, "category": "web", "parent_ens_name": "smokecreator.eth"}, expect=409)
    r = creator.post(f"/agents/{own['id']}/publish")
    assert r["mode"] == "creator" and r["agent"]["ens_name"] == f"{own['label']}.smokecreator.eth", r
    print("D1 creator-owned agent:", r["agent"]["ens_name"])
    listed = client.get("/agents")
    assert any(a["id"] == agent["id"] for a in listed)
    print("V3 marketplace lists agent")

    # --- 会社と人員（受注側）を ENS 名つきで登録
    co_admin = Client(BASE); co_admin.login()
    co_ens = "smoke-" + co_admin.address[-6:].lower() + ".eth"
    co = co_admin.post("/companies", {"name": "Smoke Co.", "ens_name": co_ens, "description": "On-site photography, in-person checks"}, expect=201)
    worker2 = Client(BASE); worker2.login()
    m1 = co_admin.post(f"/companies/{co['id']}/members", {"label": "dan", "name": "Dan", "wallet_address": worker.address, "role": "photographer", "skills": "photography,on-site check,stores,exteriors,URL", "location": "Tokyo"}, expect=201)
    m2 = co_admin.post(f"/companies/{co['id']}/members", {"label": "emi", "name": "Emi", "wallet_address": worker2.address, "role": "surveyor", "skills": "surveys,on-site check", "location": "Osaka"}, expect=201)
    assert m1["ens_name"] == f"dan.{co_ens}" and m2["ens_name"] == f"emi.{co_ens}"
    client.post(f"/companies/{co['id']}/members", {"label": "x", "name": "X", "wallet_address": client.address}, expect=403)  # 管理者以外
    print("V15 company + members:", [m["ens_name"] for m in co_admin.get(f"/companies/{co['id']}")["members"]])

    # --- 案件作成 → 計画
    # 依頼開始は World 検証つき（FR-002）。承認者は開発部(client 本人)と経理部(fin) の 2 名・必要 2
    fin = Client(BASE); fin.login()
    case = client.post("/cases", {"agent_id": agent["id"], "title": "Restaurant reservation web service", "description": "MVP in 3 days", "budget_usdc": 300,
                                  "approvers": [client.address, fin.address], "threshold": 2, "idkit_response": None}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval", "planning_failed"})
    assert case["status"] == "awaiting_approval", case
    assert case["tasks"] and any(t["type"] == "human" for t in case["tasks"])
    total = sum(t["estimated_cost"] for t in case["tasks"])
    assert total == case["budget"], (total, case["budget"])  # PM 管理費もタスクとして契約（CON-006）
    print("V4 plan:", len(case["tasks"]), "tasks (incl. PM), total == budget")

    # --- openCase（発注者の tx。モック）→ worker が工程ごとに預託
    case = client.post(f"/cases/{case['id']}/opened", {"tx_hash": fake_tx()})
    assert case["status"] == "in_progress"
    for _ in range(60):
        case = client.get(f"/cases/{case['id']}")
        if all(t["chain_status"] in ("funded", "submitted", "paid") for t in case["tasks"]):
            break
        time.sleep(0.5)
    assert all(t["chain_status"] != "none" for t in case["tasks"]), [t["chain_status"] for t in case["tasks"]]
    print("V5 each task funded via worker; project subname:", case["project_ens_name"])
    # AI タスクが終わり、human タスクだけ残るまで待つ
    for _ in range(60):
        case = client.get(f"/cases/{case['id']}")
        ai_done = all(t["status"] == "done" for t in case["tasks"] if t["type"] == "ai")
        if ai_done:
            break
        time.sleep(0.5)
    assert ai_done, case["tasks"]
    print("V6 ai tasks done")

    # --- Human Task: PM Agent が ENS 上の人員から指名 → 本人が受諾
    ht = next(t for t in case["tasks"] if t["type"] == "human")["human_task"]
    assert ht["status"] == "assigned" and ht["assignee"], ht
    print("V16 assigned to", ht["assignee"]["ens_name"], "-", ht["assignment_reason"])
    assert any(n["kind"] == "assigned" for n in worker.get("/cases/notifications"))  # A2: 指名の通知
    assert ht["assignee"]["ens_name"] == f"dan.{co_ens}", ht["assignee"]  # スキル一致で Dan
    assert not any(t["id"] == ht["id"] for t in worker.get("/human-tasks"))  # 指名中は公開一覧に出ない
    assert any(t["id"] == ht["id"] for t in worker.get("/human-tasks/assigned"))
    client.post(f"/human-tasks/{ht['id']}/accept", {}, expect=403)  # 発注者は受注不可
    worker2.post(f"/human-tasks/{ht['id']}/accept", {}, expect=403)  # 指名されていない人員は受諾不可
    # 辞退 → 次の候補（Emi）に再指名 → Emi も辞退 → 公開募集
    ht = worker.post(f"/human-tasks/{ht['id']}/decline", {})
    assert ht["status"] == "assigned" and ht["assignee"]["ens_name"] != f"dan.{co_ens}", ht
    # 残りの候補が辞退し続けると最終的に公開募集になる（seed 済みの他社人員がいる場合はそちらにも回る）
    for _ in range(10):
        if ht["status"] != "assigned":
            break
        addr = ht["assignee"]["wallet_address"]
        c = next((x for x in (worker, worker2) if x.address.lower() == addr), None)
        if c is None:
            # seed のデモログイン人員に指名された場合は、そのロールでログインして辞退する
            for u in worker.get("/auth/dev-users"):
                dc = Client(BASE)
                r = dc.http.post("/auth/dev-login", json={"role": u["role"]}).json()
                if r["user"]["wallet_address"] == addr:
                    dc.http.headers["Authorization"] = f"Bearer {r['token']}"
                    c = dc
                    break
        if c is None:
            print("   assigned to an unknown member; stopping decline loop at", ht["assignee"]["ens_name"])
            break
        ht = c.post(f"/human-tasks/{ht['id']}/decline", {})
    print("V17 decline → reassign ok (final status:", ht["status"] + ")")
    assert ht["status"] == "open" and ht["assignee"] is None, ht
    ht = worker.post(f"/human-tasks/{ht['id']}/accept", {"idkit_response": None})
    assert ht["status"] == "accepted"
    ht = worker.post(f"/human-tasks/{ht['id']}/submit", {"submission": "https://example.com/photo1.jpg 3 exterior photos"})
    assert ht["status"] == "done"
    case = client.wait(f"/cases/{case['id']}", "status", {"delivered"})
    for _ in range(60):
        case = client.get(f"/cases/{case['id']}")
        if all(t["chain_status"] == "submitted" for t in case["tasks"]):
            break
        time.sleep(0.5)
    assert all(t["chain_status"] == "submitted" and t["deliverable_hash"] for t in case["tasks"]), [(t["title"], t["chain_status"]) for t in case["tasks"]]
    ht_task = next(t for t in case["tasks"] if t["type"] == "human")
    assert ht_task["payee"] == worker.address.lower()  # Human Task の支払先は worker
    print("V7 human task done; all tasks submitted with deliverable hashes; case delivered")
    team = client.get(f"/cases/{case['id']}/team")
    assert len(team) == len(case["tasks"])
    ai = [t for t in team if t["kind"] == "ai" and t["role"] != "pm"]
    assert all(t["assignee_ens"].endswith(f".{agent['ens_name']}") for t in ai), [t["assignee_ens"] for t in ai]
    hum = next(t for t in team if t["kind"] == "human")
    assert hum["candidates"] and any(x["declined"] for x in hum["candidates"]) and hum["assignee_ens"].startswith("worker:")
    print("V20 team endpoint: subagent names + real candidates (declined marked)")

    # --- C1/A2: 承認者の承認待ち一覧と通知
    pend = fin.get("/cases/pending-approvals")
    assert len(pend) == len(case["tasks"]), (len(pend), len(case["tasks"]))
    assert any(n["kind"] == "approve" and n["urgent"] for n in fin.get("/cases/notifications"))
    assert j1.get("/cases/pending-approvals") == []  # 承認者でない
    print("C1/A2 pending approvals:", len(pend), "notices ok")

    # --- 承認（World 検証 + EIP-712 署名）。1 人目で保留、2 人目で自動支払い
    t0 = case["tasks"][0]
    typed = client.get(f"/cases/{case['id']}/tasks/{t0['id']}/typed-data")
    j1.post(f"/cases/{case['id']}/tasks/{t0['id']}/approve", {"signature": sign_typed(j1, typed), "idkit_response": None}, expect=403)  # 承認者以外
    client.post(f"/cases/{case['id']}/tasks/{t0['id']}/approve", {"signature": sign_typed(fin, typed), "idkit_response": None}, expect=400)  # 他人の署名
    for t in case["tasks"]:
        typed = client.get(f"/cases/{case['id']}/tasks/{t['id']}/typed-data")
        client.post(f"/cases/{case['id']}/tasks/{t['id']}/approve", {"signature": sign_typed(client, typed), "idkit_response": None})
    client.post(f"/cases/{case['id']}/tasks/{t0['id']}/approve", {"signature": sign_typed(client, typed), "idkit_response": None}, expect=409)  # 二重承認
    time.sleep(2)
    case = client.get(f"/cases/{case['id']}")
    assert all(t["approval_count"] == 1 and t["chain_status"] == "submitted" for t in case["tasks"]), "Should be on hold at 1/2 (FR-013)"
    assert case["status"] == "delivered"
    assert client.get("/cases/pending-approvals") == []  # 自分の分は承認済みなので消える
    for t in case["tasks"]:
        typed = fin.get(f"/cases/{case['id']}/tasks/{t['id']}/typed-data")
        fin.post(f"/cases/{case['id']}/tasks/{t['id']}/approve", {"signature": sign_typed(fin, typed), "idkit_response": None})
    case = client.wait(f"/cases/{case['id']}", "status", {"completed"})
    assert all(t["chain_status"] == "paid" for t in case["tasks"])
    assert client.get(f"/agents/{agent['id']}")["completed_count"] == 1
    print("V8 2/2 approvals → auto-paid per task (FR-012), case completed")

    # --- レビュー（World 検証: モック）
    rv = client.post("/reviews", {"case_id": case["id"], "rating": 5, "comment": "Great communication!", "idkit_response": None}, expect=201)
    assert rv["target_type"] == "agent"
    a = client.get(f"/agents/{agent['id']}")
    assert a["rating_count"] == 1 and float(a["rating_avg"]) == 5.0
    client.post("/reviews", {"case_id": case["id"], "rating": 1, "comment": "Duplicate post", "idkit_response": None}, expect=409)
    j1.post("/reviews", {"case_id": case["id"], "rating": 5, "idkit_response": None}, expect=403)  # 当事者以外
    wr = worker.post("/reviews", {"case_id": case["id"], "rating": 4, "comment": "Careful delivery, very helpful", "idkit_response": None}, expect=201)
    assert wr["target_type"] == "user"
    print("V9/V10 reviews ok, duplicate rejected")

    # --- 紛争 → Jury
    case2 = client.post("/cases", {"agent_id": agent["id"], "title": "Dispute test case", "description": "", "budget_usdc": 100, "idkit_response": None}, expect=201)
    case2 = client.wait(f"/cases/{case2['id']}", "status", {"awaiting_approval"})
    client.post(f"/cases/{case2['id']}/opened", {"tx_hash": fake_tx()})
    for _ in range(60):
        c2 = client.get(f"/cases/{case2['id']}")
        if all(t["status"] == "done" for t in c2["tasks"] if t["type"] == "ai"):
            break
        time.sleep(0.5)
    ht2 = next(t for t in worker.get("/human-tasks/assigned") if t["case_id"] == case2["id"])
    worker.post(f"/human-tasks/{ht2['id']}/accept", {})
    worker.post(f"/human-tasks/{ht2['id']}/submit", {"submission": "Here are the photos"})
    client.wait(f"/cases/{case2['id']}", "status", {"delivered"})
    d = client.post(f"/cases/{case2['id']}/dispute", {"reason": "Promised features are missing"}, expect=201)
    for _ in range(60):
        d = client.get(f"/disputes/{d['id']}")
        if d["summary_json"]:
            break
        time.sleep(0.5)
    assert d["summary_json"] and "issues" in d["summary_json"], d
    print("V11 dispute opened, summary:", d["summary_json"]["issues"][:1])
    client.post(f"/disputes/{d['id']}/vote", {"vote": "refund"}, expect=403)  # 当事者
    worker.post(f"/disputes/{d['id']}/vote", {"vote": "refund"}, expect=403)  # 当事者
    j1.post(f"/disputes/{d['id']}/vote", {"vote": "refund"})
    j1.post(f"/disputes/{d['id']}/vote", {"vote": "refund"}, expect=409)
    j2.post(f"/disputes/{d['id']}/vote", {"vote": "release"})
    d = j3.post(f"/disputes/{d['id']}/vote", {"vote": "refund"})
    assert d["status"] == "closed" and d["outcome"] == "refund", d
    c2 = client.wait(f"/cases/{case2['id']}", "status", {"resolved"})
    assert all(t["chain_status"] == "resolved" for t in c2["tasks"])
    print("V12 jury resolved:", d["outcome"], "→ each task resolved via worker")
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
