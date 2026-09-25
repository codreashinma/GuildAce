import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .routers import agents, auth, cases, config, disputes, human_tasks, reviews, world

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)  # MVP: マイグレーションの代わりに create_all
    yield


app = FastAPI(title="Choice — AI Agent Marketplace API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (auth, config, world, agents, cases, human_tasks, reviews, disputes):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"ok": True}
