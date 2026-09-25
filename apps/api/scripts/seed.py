"""デモ用データ投入。API を起動した状態で実行する。
使い方: .venv/bin/python scripts/seed.py [http://localhost:8001]
出力される秘密鍵はデモ用（発注者 / 作成者 / worker）。MetaMask にインポートすれば同じユーザーとして操作できる。"""

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from _client import Client, fake_tx  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001"

AGENTS = [
    {"name": "Web開発 PM Agent", "label": "web-pm", "category": "web", "fee_bps": 200,
     "description": "Web サービス / SaaS の MVP を短期間で。Next.js と TypeScript が得意。現地確認や実物レビューは World で認証された人間に発注します。",
     "rules": "1. 案件を 4〜6 タスクに分解する 2. デザイン→フロント→バックエンド→QA の順で進める 3. 実店舗の写真や利用者の感想が要る場合は Human Task にする 4. 成果物は Markdown で具体的に書く"},
    {"name": "デザイン PM Agent", "label": "design-pm", "category": "design", "fee_bps": 300,
     "description": "ブランド・UI・LP のデザイン案件を編成。人間のデザイナーによる最終確認を必ず入れます。",
     "rules": "1. リサーチ→コンセプト→ビジュアル→仕上げの順 2. 最終チェックは人間に依頼する"},
    {"name": "Wedding PM Agent", "label": "wedding-pm", "category": "wedding", "fee_bps": 300,
     "description": "結婚式の準備を段取り。会場の下見や試食は人間タスクとして発注します。",
     "rules": "1. 会場・衣装・招待状・当日進行に分解 2. 現地で確認が必要なものはすべて Human Task にする"},
]


def main() -> None:
    creator, client, worker = Client(BASE), Client(BASE), Client(BASE)
    for c in (creator, client, worker):
        c.login()
    print("creator:", creator.address, creator.acct.key.to_0x_hex())
    print("client: ", client.address, client.acct.key.to_0x_hex())
    print("worker: ", worker.address, worker.acct.key.to_0x_hex())

    agents = []
    for a in AGENTS:
        try:
            ag = creator.post("/agents", a, expect=201)
        except AssertionError:
            print("skip existing", a["label"])
            continue
        ag = creator.post(f"/agents/{ag['id']}/publish")
        ag = creator.wait(f"/agents/{ag['id']}", "status", {"published", "publish_failed"}, timeout=300)
        print("published", ag["ens_name"], ag["status"], ag.get("ens_error") or "")
        agents.append(ag)

    if not agents:
        return
    # 完了済み案件 + レビューを 1 件作る（Web PM の実績用）
    web = agents[0]
    import time
    case = client.post("/cases", {"agent_id": web["id"], "title": "レストラン予約 Web サービス", "description": "3 日で MVP を作りたい。予算 300 USDC", "budget_usdc": 300}, expect=201)
    case = client.wait(f"/cases/{case['id']}", "status", {"awaiting_approval", "planning_failed"}, timeout=120)
    if case["status"] != "awaiting_approval":
        print("planning failed", case.get("error"))
        return
    if client.get("/config")["mock"]["chain"]:
        client.post(f"/cases/{case['id']}/funded", {"tx_hash": fake_tx()})
        for _ in range(120):
            c = client.get(f"/cases/{case['id']}")
            if all(t["status"] == "done" for t in c["tasks"] if t["type"] == "ai"):
                break
            time.sleep(1)
        for ht in worker.get("/human-tasks"):
            if ht["case_id"] == case["id"]:
                worker.post(f"/human-tasks/{ht['id']}/accept", {})
                worker.post(f"/human-tasks/{ht['id']}/submit", {"submission": "https://example.com/photos/store-1.jpg ほか 3 枚を撮影しました。"})
        client.wait(f"/cases/{case['id']}", "status", {"delivered"}, timeout=120)
        client.post(f"/cases/{case['id']}/released", {"tx_hash": fake_tx()})
        client.post("/reviews", {"case_id": case["id"], "rating": 5, "comment": "良いコミュニケーションでした！タスク分解が的確。"}, expect=201)
        print("demo case completed + reviewed:", case["id"])
    else:
        print("chain が有効なので案件は承認待ちのまま:", case["id"])
    print("seed done")


if __name__ == "__main__":
    main()
