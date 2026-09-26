import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .db import Base, engine
from .routers import agents, auth, case_audit, cases, companies, config, disputes, ens, human_tasks, me, ops, reviews, world

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)  # MVP: マイグレーションの代わりに create_all
    _migrate()
    s = get_settings()
    log = logging.getLogger("choice")
    if s.jwt_secret == "dev-secret-change-me":
        log.warning("JWT_SECRET が既定値のままです。公開環境では必ずランダムな値に変えてください（トークン偽造が可能）")
    if s.dev_login_enabled and s.chain_enabled:
        log.warning("DEV_LOGIN_ENABLED=true かつ実チェーン設定です。デモログインのユーザーは署名できず、Jury 3 票で resolve が実行できます。公開環境では false にしてください")
    from .services import worker

    worker.start()  # チェーン連携ワーカー（ADR-006）
    yield


def _migrate() -> None:
    """create_all では変わらない既存 DB の制約を、冪等に直す。
    2026-09-26: agents.label の単独 UNIQUE を (label, coalesce(parent_ens_name,'')) の UNIQUE に変更（Creator 所有の Agent と同じラベルを許す）"""
    with engine.begin() as conn:
        idx = {r[0]: r[1] for r in conn.execute(text("select indexname, indexdef from pg_indexes where tablename = 'agents'"))}
        if "ix_agents_label" in idx and "UNIQUE" in idx["ix_agents_label"]:
            conn.execute(text("drop index ix_agents_label"))
            conn.execute(text("create index ix_agents_label on agents (label)"))
            logging.getLogger("choice").info("migrate: agents.label の単独 UNIQUE を解除")
        if "uq_agents_label_parent" not in idx:
            conn.execute(text("create unique index uq_agents_label_parent on agents (label, coalesce(parent_ens_name, ''))"))
            logging.getLogger("choice").info("migrate: uq_agents_label_parent を作成")
        # 2026-09-26: 専門 AI エージェントの一覧（agents.subagents）。旧 subagent_rules（{role: prompt}）があれば既定の 4 つに乗せて移す
        cols = {r[0] for r in conn.execute(text("select column_name from information_schema.columns where table_name = 'agents'"))}
        if "subagents" not in cols:
            conn.execute(text("alter table agents add column subagents json"))
            logging.getLogger("choice").info("migrate: agents.subagents を追加")
        if "subagent_rules" in cols:
            import json

            from .services.ens import DEFAULT_SUBAGENTS

            rows = conn.execute(text("select id, subagent_rules from agents where subagent_rules is not null and subagents is null")).all()
            for aid, rules in rows:
                rules = rules if isinstance(rules, dict) else json.loads(rules or "{}")
                subs = [{**d, "rules": rules.get(d["role"], "")} for d in DEFAULT_SUBAGENTS]
                conn.execute(text("update agents set subagents = :v where id = :id"), {"v": json.dumps(subs, ensure_ascii=False), "id": aid})
            conn.execute(text("alter table agents drop column subagent_rules"))
            logging.getLogger("choice").info("migrate: agents.subagent_rules を subagents に移して削除（%d 件）", len(rows))


app = FastAPI(title="Choice — AI Agent Marketplace API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, config, world, ens, agents, cases, case_audit, companies, human_tasks, reviews, disputes, me, ops):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"ok": True}
