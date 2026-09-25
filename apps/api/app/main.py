import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routers import agents, auth, cases, companies, config, disputes, ens, human_tasks, reviews, world

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)  # MVP: マイグレーションの代わりに create_all
    s = get_settings()
    log = logging.getLogger("choice")
    if s.jwt_secret == "dev-secret-change-me":
        log.warning("JWT_SECRET が既定値のままです。公開環境では必ずランダムな値に変えてください（トークン偽造が可能）")
    if s.dev_login_enabled and s.chain_enabled:
        log.warning("DEV_LOGIN_ENABLED=true かつ実チェーン設定です。デモログインのユーザーは署名できず、Jury 3 票で resolve が実行できます。公開環境では false にしてください")
    from .services import worker

    worker.start()  # チェーン連携ワーカー（ADR-006）
    yield


app = FastAPI(title="Choice — AI Agent Marketplace API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, config, world, ens, agents, cases, companies, human_tasks, reviews, disputes):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"ok": True}
