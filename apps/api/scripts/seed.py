"""デモ用データ投入。API を起動した状態で実行する。
使い方: .venv/bin/python scripts/seed.py [http://localhost:8001]
出力される秘密鍵はデモ用（発注者 / 作成者 / worker）。MetaMask にインポートすれば同じユーザーとして操作できる。"""

import sys

import httpx

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _client import Client, fake_tx, sign_typed  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"

AGENTS = [
    {"name": "Web Dev PM Agent", "label": "web-pm", "category": "web", "fee_bps": 200,
     "description": "Ships MVPs for web services / SaaS fast. Strong in Next.js and TypeScript. On-site checks and hands-on reviews are requested from World-verified humans.",
     "rules": "1. Break the case down into 4-6 tasks 2. Proceed in the order design -> frontend -> backend -> QA 3. Use a Human Task when photos of a physical store or user feedback are needed 4. Write deliverables concretely in Markdown",
     "subagents": [
         {"role": "designer", "name": "Designer Agent", "description": "Screen structure, wireframes, and design direction", "rules": "List of screens and wireframes as Markdown tables. Black-and-white color scheme"},
         {"role": "frontend", "name": "Frontend Agent", "description": "Screen implementation approach and component design", "rules": "Next.js + TypeScript. Include a component list and the key implementation code"},
         {"role": "backend", "name": "Backend Agent", "description": "API design and data model", "rules": "FastAPI. Endpoint table (method, path, input/output) and DB table definitions"},
         {"role": "qa", "name": "QA Agent", "description": "Acceptance test criteria and results", "rules": "A table of steps, expected results, and a result column for each acceptance criterion"},
         {"role": "copywriter", "name": "Copywriter Agent", "description": "Copy for landing pages and service descriptions", "rules": "Headline, lead, then body. Start with one line stating the target audience and key message"}]},
    {"name": "Design PM Agent", "label": "design-pm", "category": "design", "fee_bps": 300,
     "description": "Organizes brand, UI, and landing page design cases. Always includes a final check by a human designer.",
     "rules": "1. Proceed in the order research -> concept -> visuals -> finishing 2. Request the final check from a human"},
    {"name": "Wedding PM Agent", "label": "wedding-pm", "category": "wedding", "fee_bps": 300,
     "description": "Plans wedding preparations. Venue visits and tastings are requested as Human Tasks.",
     "rules": "1. Break down into venue, attire, invitations, and day-of schedule 2. Make everything that needs an on-site check a Human Task"},
]


def main() -> None:
    creator, client, worker = Client(BASE), Client(BASE), Client(BASE)
    for c in (creator, client, worker):
        c.login()
    print("creator:", creator.address, creator.acct.key.to_0x_hex())
    print("client: ", client.address, client.acct.key.to_0x_hex())
    print("worker: ", worker.address, worker.acct.key.to_0x_hex())

    # デモログイン（DEV_LOGIN_ENABLED）が有効なら、Agent の作成者を「Agent 作成者」ロールにする（デモログインで Agent 管理と収益が見える）
    try:
        r = httpx.post(f"{BASE}/auth/dev-login", json={"role": "creator"}, timeout=30)
        if r.status_code == 200:
            creator.http.headers["Authorization"] = f"Bearer {r.json()['token']}"
            print("creator = demo login \"Agent creator\":", r.json()["user"]["wallet_address"])
    except Exception:  # noqa: BLE001
        pass

    # デモログイン（DEV_LOGIN_ENABLED）が有効なら、「Human Task worker」ロールの固定アドレスを Dan にする
    try:
        r = httpx.post(f"{BASE}/auth/dev-login", json={"role": "worker"}, timeout=30)
        if r.status_code == 200:
            dan_address = r.json()["user"]["wallet_address"]
            worker.http.headers["Authorization"] = f"Bearer {r.json()['token']}"  # 以降 worker はデモログインの worker として操作
        else:
            dan_address = worker.address
    except Exception:  # noqa: BLE001
        dan_address = worker.address
    if dan_address != worker.address:
        print("dan = demo login worker:", dan_address)

    # 受注側の会社と人員（ENS: <label>.field-co.eth）
    co_admin = Client(BASE); co_admin.login()
    print("company admin:", co_admin.address, co_admin.acct.key.to_0x_hex())
    try:
        co = co_admin.post("/companies", {"name": "Field Co.", "ens_name": "field-co.eth", "description": "A company specializing in on-site photography, in-person checks, and event coverage"}, expect=201)
        for m in [
            {"label": "dan", "name": "Dan", "wallet_address": dan_address, "role": "photographer", "skills": "photography,on-site check,stores,exteriors", "location": "Tokyo"},
            {"label": "emi", "name": "Emi", "wallet_address": Client(BASE).address, "role": "surveyor", "skills": "surveys,on-site check,interviews", "location": "Osaka"},
            {"label": "ken", "name": "Ken", "wallet_address": Client(BASE).address, "role": "reporter", "skills": "event coverage,video shooting", "location": "Fukuoka", "available": False},
        ]:
            co_admin.post(f"/companies/{co['id']}/members", m, expect=201)
        print("company:", co["ens_name"], "members: dan/emi/ken")
    except AssertionError:
        print("company exists")

    agents = []
    for a in AGENTS:
        try:
            ag = creator.post("/agents", a, expect=201)
        except AssertionError:
            print("skip existing", a["label"])
            continue
        ag = creator.post(f"/agents/{ag['id']}/publish")["agent"]
        ag = creator.wait(f"/agents/{ag['id']}", "status", {"published", "publish_failed"}, timeout=300)
        print("published", ag["ens_name"], ag["status"], ag.get("ens_error") or "")
        agents.append(ag)

    if not agents:
        return
    # 完了済み案件 + レビューを 1 件作る（Web PM の実績用）
    web = agents[0]
    import time
    case = client.post("/cases", {"agent_id": web["id"], "title": "Restaurant reservation web service", "description": "We want an MVP in 3 days. Budget: 300 USDC", "budget_usdc": 300, "idkit_response": None}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval", "planning_failed"}, timeout=120)
    if case["status"] != "awaiting_approval":
        print("planning failed", case.get("error"))
        return
    if client.get("/config")["mock"]["chain"]:
        client.post(f"/cases/{case['id']}/opened", {"tx_hash": fake_tx()})
        for _ in range(120):
            c = client.get(f"/cases/{case['id']}")
            if all(t["status"] == "done" for t in c["tasks"] if t["type"] == "ai"):
                break
            time.sleep(1)
        for ht in worker.get("/human-tasks/assigned") + worker.get("/human-tasks"):
            if ht["case_id"] == case["id"]:
                worker.post(f"/human-tasks/{ht['id']}/accept", {})
                worker.post(f"/human-tasks/{ht['id']}/submit", {"submission": "Took 3 photos, including https://example.com/photos/store-1.jpg."})
        client.wait(f"/cases/{case['id']}", "status", {"delivered"}, timeout=120)
        for _ in range(60):
            c = client.get(f"/cases/{case['id']}")
            if all(t["chain_status"] == "submitted" for t in c["tasks"]):
                break
            time.sleep(1)
        for t in c["tasks"]:
            typed = client.get(f"/cases/{case['id']}/tasks/{t['id']}/typed-data")
            client.post(f"/cases/{case['id']}/tasks/{t['id']}/approve", {"signature": sign_typed(client, typed), "idkit_response": None})
        client.wait(f"/cases/{case['id']}", "status", {"completed"}, timeout=120)
        client.post("/reviews", {"case_id": case["id"], "rating": 5, "comment": "Great communication! The task breakdown was spot on."}, expect=201)
        print("demo case completed + reviewed:", case["id"])

        # --- 収益・運用のデモ用: 差し戻し → Jury 3 票で返金（PM 管理費は「裁定済・受取 0」になる）
        juries = []
        for role in ("jury1", "jury2", "jury3"):
            r = httpx.post(f"{BASE}/auth/dev-login", json={"role": role}, timeout=30)
            if r.status_code != 200:
                break
            j = Client(BASE)
            j.http.headers["Authorization"] = f"Bearer {r.json()['token']}"
            juries.append(j)
        if len(juries) == 3:
            case2 = client.post("/cases", {"agent_id": web["id"], "title": "Internal portal redesign", "description": "Refresh the existing portal UI and improve search. Budget: 120 USDC", "budget_usdc": 120, "idkit_response": None}, expect=201)
            case2 = client.wait(f"/cases/{case2['id']}", "status", {"awaiting_approval", "planning_failed"}, timeout=120)
            if case2["status"] == "awaiting_approval":
                client.post(f"/cases/{case2['id']}/opened", {"tx_hash": fake_tx()})
                for _ in range(120):
                    c2 = client.get(f"/cases/{case2['id']}")
                    if all(t["chain_status"] in ("submitted", "funded") for t in c2["tasks"]) and any(t["chain_status"] == "submitted" for t in c2["tasks"]):
                        break
                    time.sleep(1)
                d = client.post(f"/cases/{case2['id']}/dispute", {"reason": "Search does not work as specified. The design also differs from what was requested"}, expect=201)
                for j, v in zip(juries, ("refund", "release", "refund")):
                    d = j.post(f"/disputes/{d['id']}/vote", {"vote": v})
                client.wait(f"/cases/{case2['id']}", "status", {"resolved"}, timeout=120)
                print("demo case refunded by jury:", case2["id"])
        else:
            print("Demo login is disabled, skipping the refund case")

        # --- 進行中の案件（PM 管理費が「預託中」に出る）
        case3 = client.post("/cases", {"agent_id": web["id"], "title": "Recruiting site landing page", "description": "A one-page landing page for engineer recruiting. Budget: 80 USDC", "budget_usdc": 80, "idkit_response": None}, expect=201)
        case3 = client.wait(f"/cases/{case3['id']}", "status", {"awaiting_approval", "planning_failed"}, timeout=120)
        if case3["status"] == "awaiting_approval":
            client.post(f"/cases/{case3['id']}/opened", {"tx_hash": fake_tx()})
            print("demo case in progress:", case3["id"])
    else:
        print("Chain is enabled, so the case stays awaiting approval:", case["id"])
    print("seed done")
    print("Failed jobs for the Ops screen (/ops/jobs) can be created with scripts/seed_ops.py (it writes to the DB directly, so pass DATABASE_URL)")


if __name__ == "__main__":
    main()
