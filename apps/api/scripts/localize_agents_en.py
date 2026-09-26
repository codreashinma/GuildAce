"""デモ用: seed 済みの PM Agent の表示文（名前・説明・進め方・専門 Agent の説明）を英語版 seed の文言に揃える。
DB を直接更新し、platform 所有の Agent は PATCH /agents と同じ経路で ENS の text record 再書き込みをワーカーに投入する
（description と専門 Agent の description）。Creator 所有の Agent は DB の表示文だけ更新する（ENS は Creator の署名が要るため触らない）。
使い方（apps/api で。本番に流すときは DATABASE_URL を渡す）:
  .venv/bin/python scripts/localize_agents_en.py
  DATABASE_URL=postgresql+psycopg://... .venv/bin/python scripts/localize_agents_en.py
冪等。すでに英語なら何もしない。"""

import hashlib
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
sys.path.insert(0, __file__.rsplit("/", 2)[0])
from seed import AGENTS  # noqa: E402  英語版 seed の文言をそのまま使う

from app.db import SessionLocal  # noqa: E402
from app.models import Agent  # noqa: E402
from app.routers.agents import agent_on_ens, ens_update_job, profile_texts  # noqa: E402
from app.services import ens, worker  # noqa: E402

# Creator 所有のテスト用 Agent（label → 表示文）。ENS には書かない
CREATOR_OWNED = {
    "web-pm": {"name": "Web Dev PM Agent", "description": "Test PM agent for the demo. Runs web projects with designer, frontend, backend, and QA agents under its own ENS namespace."},
}


def main() -> None:
    db = SessionLocal()
    try:
        by_label = {a["label"]: a for a in AGENTS}
        for agent in db.query(Agent).filter(Agent.status == "published").order_by(Agent.created_at).all():
            if agent.owner_mode == "platform" and agent.label in by_label:
                src = by_label[agent.label]
                before = profile_texts(agent)
                agent.name, agent.description, agent.rules = src["name"], src["description"], src["rules"]
                # ENS 上に既にある 4 つの subname だけを英語にする（新しい subname は発行しない）
                new_subs = [dict(x) for x in ens.DEFAULT_SUBAGENTS]
                agent.subagents = new_subs
                db.flush()
                diff = {k: v for k, v in profile_texts(agent).items() if before.get(k) != v}
                # DB が未設定（既定）でも ENS 上の record は日本語のままなので、既定の 4 つは常に書き直す（ジョブは内容で冪等）
                sub_changed = new_subs
                db.commit()
                queued = []
                if agent_on_ens(agent):
                    if diff:
                        ens_update_job(db, agent, diff)
                        queued.append("ens_update")
                    if sub_changed:
                        key = "ens_subagents:" + agent.id + ":" + hashlib.sha256(repr(sorted((x["role"], x.get("name", ""), x.get("description", "")) for x in sub_changed)).encode()).hexdigest()[:16]
                        worker.enqueue(db, "ens_subagents", key[:200], {"agent_id": agent.id, "label": agent.label, "subagents": sub_changed})
                        queued.append(f"ens_subagents({len(sub_changed)})")
                print(f"platform  {agent.ens_name}: name/description/rules updated; ENS jobs: {', '.join(queued) or 'none (not on ENS or no change)'}")
            elif agent.owner_mode == "creator" and agent.label in CREATOR_OWNED:
                src = CREATOR_OWNED[agent.label]
                agent.name, agent.description = src["name"], src["description"]
                db.commit()
                print(f"creator   {agent.ens_name}: name/description updated in DB only (ENS needs the creator's signature)")
            else:
                print(f"skip      {agent.ens_name}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
