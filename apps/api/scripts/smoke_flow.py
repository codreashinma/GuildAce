"""モックモードで全フローを通すスモークテスト。
使い方: API を起動した状態で `.venv/bin/python scripts/smoke_flow.py [http://localhost:8001]`"""

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _client import Client, fake_tx  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"


def main() -> None:
    creator, client, worker, j1, j2, j3 = (Client(BASE) for _ in range(6))
    for c in (creator, client, worker, j1, j2, j3):
        c.login()
    print("V1 login ok:", client.address)

    # --- Agent 作成・公開
    label = "web-pm-" + creator.address[-6:].lower()
    agent = creator.post("/agents", {"name": "Web開発 PM Agent", "label": label, "description": "Web サービスを 3 日で作る", "category": "web",
                                     "rules": "タスクは小さく分解し、現地確認は人間に任せる", "fee_bps": 200}, expect=201)
    agent = creator.post(f"/agents/{agent['id']}/publish")
    agent = creator.wait(f"/agents/{agent['id']}", "status", {"published", "publish_failed"})
    assert agent["status"] == "published", agent
    assert agent["ens_name"] == f"{label}.choice.eth"
    print("V2 agent published:", agent["ens_name"], agent["ens_tx_hash"][:12])
    listed = client.get("/agents")
    assert any(a["id"] == agent["id"] for a in listed)
    print("V3 marketplace lists agent")

    # --- 会社と人員（受注側）を ENS 名つきで登録
    co_admin = Client(BASE); co_admin.login()
    co = co_admin.post("/companies", {"name": "Field Co.", "ens_name": "field-co.eth", "description": "現地撮影・実物確認"}, expect=201)
    worker2 = Client(BASE); worker2.login()
    m1 = co_admin.post(f"/companies/{co['id']}/members", {"label": "dan", "name": "Dan", "wallet_address": worker.address, "role": "photographer", "skills": "写真撮影,現地確認,店舗", "location": "東京"}, expect=201)
    m2 = co_admin.post(f"/companies/{co['id']}/members", {"label": "emi", "name": "Emi", "wallet_address": worker2.address, "role": "surveyor", "skills": "アンケート,現地確認", "location": "大阪"}, expect=201)
    assert m1["ens_name"] == "dan.field-co.eth" and m2["ens_name"] == "emi.field-co.eth"
    client.post(f"/companies/{co['id']}/members", {"label": "x", "name": "X", "wallet_address": client.address}, expect=403)  # 管理者以外
    print("V15 company + members:", [m["ens_name"] for m in co_admin.get(f"/companies/{co['id']}")["members"]])

    # --- 案件作成 → 計画
    case = client.post("/cases", {"agent_id": agent["id"], "title": "レストラン予約 Web サービス", "description": "3 日で MVP", "budget_usdc": 300}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval", "planning_failed"})
    assert case["status"] == "awaiting_approval", case
    assert case["tasks"] and any(t["type"] == "human" for t in case["tasks"])
    total = sum(t["estimated_cost"] for t in case["tasks"])
    assert total <= case["budget"], (total, case["budget"])
    print("V4 plan:", len(case["tasks"]), "tasks, cost", total)

    # --- 入金（モック tx）→ 実行
    case = client.post(f"/cases/{case['id']}/funded", {"tx_hash": fake_tx()})
    assert case["status"] == "in_progress"
    print("V5 funded")
    # AI タスクが終わり、human タスクだけ残るまで待つ
    import time
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
    assert ht["assignee"]["ens_name"] == "dan.field-co.eth"  # スキル一致で Dan
    assert not any(t["id"] == ht["id"] for t in worker.get("/human-tasks"))  # 指名中は公開一覧に出ない
    assert any(t["id"] == ht["id"] for t in worker.get("/human-tasks/assigned"))
    client.post(f"/human-tasks/{ht['id']}/accept", {}, expect=403)  # 発注者は受注不可
    worker2.post(f"/human-tasks/{ht['id']}/accept", {}, expect=403)  # 指名されていない人員は受諾不可
    # 辞退 → 次の候補（Emi）に再指名 → Emi も辞退 → 公開募集
    ht = worker.post(f"/human-tasks/{ht['id']}/decline", {})
    assert ht["status"] == "assigned" and ht["assignee"]["ens_name"] == "emi.field-co.eth", ht
    ht = worker2.post(f"/human-tasks/{ht['id']}/decline", {})
    assert ht["status"] == "open" and ht["assignee"] is None, ht
    print("V17 decline → reassign → open ok")
    ht = worker.post(f"/human-tasks/{ht['id']}/accept", {"idkit_response": None})
    assert ht["status"] == "accepted"
    ht = worker.post(f"/human-tasks/{ht['id']}/submit", {"submission": "https://example.com/photo1.jpg 外観 3 枚"})
    assert ht["status"] == "done"
    case = client.wait(f"/cases/{case['id']}", "status", {"delivered"})
    print("V7 human task done, case delivered. split:", case["split"])
    assert sum(int(s["amount"]) for s in case["split"]) == case["budget"]
    assert any(s["address"] == worker.address.lower() for s in case["split"])

    # --- 支払い
    case = client.post(f"/cases/{case['id']}/released", {"tx_hash": fake_tx()})
    assert case["status"] == "completed"
    assert client.get(f"/agents/{agent['id']}")["completed_count"] == 1
    print("V8 released, completed_count=1")

    # --- レビュー（World 検証: モック）
    rv = client.post("/reviews", {"case_id": case["id"], "rating": 5, "comment": "良いコミュニケーションでした！", "idkit_response": None}, expect=201)
    assert rv["target_type"] == "agent"
    a = client.get(f"/agents/{agent['id']}")
    assert a["rating_count"] == 1 and float(a["rating_avg"]) == 5.0
    client.post("/reviews", {"case_id": case["id"], "rating": 1, "comment": "二重投稿", "idkit_response": None}, expect=409)
    j1.post("/reviews", {"case_id": case["id"], "rating": 5, "idkit_response": None}, expect=403)  # 当事者以外
    wr = worker.post("/reviews", {"case_id": case["id"], "rating": 4, "comment": "納品が丁寧で助かりました", "idkit_response": None}, expect=201)
    assert wr["target_type"] == "user"
    print("V9/V10 reviews ok, duplicate rejected")

    # --- 紛争 → Jury
    case2 = client.post("/cases", {"agent_id": agent["id"], "title": "紛争テスト案件", "description": "", "budget_usdc": 100}, expect=201)
    case2 = client.wait(f"/cases/{case2['id']}", "status", {"awaiting_approval"})
    client.post(f"/cases/{case2['id']}/funded", {"tx_hash": fake_tx()})
    for _ in range(60):
        c2 = client.get(f"/cases/{case2['id']}")
        if all(t["status"] == "done" for t in c2["tasks"] if t["type"] == "ai"):
            break
        time.sleep(0.5)
    ht2 = next(t for t in worker.get("/human-tasks/assigned") if t["case_id"] == case2["id"])
    worker.post(f"/human-tasks/{ht2['id']}/accept", {})
    worker.post(f"/human-tasks/{ht2['id']}/submit", {"submission": "写真です"})
    client.wait(f"/cases/{case2['id']}", "status", {"delivered"})
    d = client.post(f"/cases/{case2['id']}/dispute", {"reason": "約束した機能が足りない"}, expect=201)
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
    assert d["resolve_tx_hash"]
    assert client.get(f"/cases/{case2['id']}")["status"] == "resolved"
    print("V12 jury resolved:", d["outcome"], d["resolve_tx_hash"][:12])
    print("\nALL SMOKE CHECKS PASSED")


if __name__ == "__main__":
    main()
