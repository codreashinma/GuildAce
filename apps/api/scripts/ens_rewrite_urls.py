"""APP_URL / API_URL を変えた後に、ENS 上の `url` と `codrea.agent.endpoint` を現在の値で書き直す。
platform 所有の Agent は worker（Owner 鍵）が書く。Creator 所有の Agent は Creator の署名が要るので一覧だけ出す（Agent 編集画面で保存し直す）。
使い方: .venv/bin/python scripts/ens_rewrite_urls.py [--dry-run]"""

import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Agent  # noqa: E402
from app.routers.agents import agent_on_ens, ens_update_job, profile_texts  # noqa: E402
from app.services import ens  # noqa: E402

DRY = "--dry-run" in sys.argv


def main() -> None:
    s = get_settings()
    print("APP_URL =", s.app_url, "/ API_URL =", s.api_url)
    if "localhost" in s.app_url or "localhost" in s.api_url:
        print("!! APP_URL / API_URL in .env are still localhost. Change them to public URLs before running")
    db = SessionLocal()
    try:
        agents = db.query(Agent).filter(Agent.status == "published").all()
        for a in agents:
            if not agent_on_ens(a):
                continue
            want = {k: v for k, v in profile_texts(a).items() if k in ("url", "codrea.agent.endpoint")}
            cur = ens.read_texts(a.ens_name, list(want), ttl=0)
            diff = {k: v for k, v in want.items() if cur.get(k) != v}
            if not diff:
                print(f"ok      {a.ens_name}")
                continue
            if a.owner_mode == "creator":
                print(f"manual  {a.ens_name}: the Creator needs to save again on the Agent edit screen -> {diff}")
                continue
            print(f"{'plan' if DRY else 'queue'}   {a.ens_name}: {diff}")
            if not DRY:
                ens_update_job(db, a, diff)
        db.commit()
    finally:
        db.close()
    if not DRY:
        print("The worker will write them within 1-2 minutes. Check: scripts/ens_check.py <name>")


if __name__ == "__main__":
    main()
