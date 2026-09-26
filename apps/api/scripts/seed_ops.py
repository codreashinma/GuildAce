"""運用画面（G1 /ops/jobs）のデモ用データ。chain_jobs に「失敗」「再送待ち」のジョブを作る。
API ではなく DB に直接書くので、API と同じ DATABASE_URL を渡す（.env があればそれを読む）。
使い方: DATABASE_URL=... .venv/bin/python scripts/seed_ops.py
先に scripts/seed.py（または画面操作）で Agent の公開や案件の預託を済ませ、確定（done）のジョブがある状態で実行する。

作るもの（冪等。既にあれば作らない）:
  1. ens_update の失敗ジョブ: RPC の 429 で 5 回失敗した体。再投入すると同じ record を書き直して確定する（実チェーンでもガス少額）
  2. fund_task の失敗ジョブ: 受信確認のタイムアウトで失敗した体。実チェーンではオンチェーンが既に funded なので再投入は 409（反映済み判定のデモ）、モックでは確定する
  3. submit の再送待ちジョブ: 次の自動再送が 10 分後。「再投入」ボタンが出ないことを見せる
"""

import sys
from datetime import UTC, datetime, timedelta

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from sqlalchemy import func  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import ChainJob  # noqa: E402

DEMO_TAG = "[demo]"
ERRORS = {
    "ens_update": "HTTPError: 429 Client Error: Too Many Requests for url: https://ethereum-sepolia-rpc.publicnode.com (RPC rate limit. All 5 attempts failed)",
    "fund_task": "TimeExhausted: Transaction 0x7d2c…a41e is not in the chain after 240 seconds (Receipt confirmation timed out. The tx itself was sent)",
}


def main() -> None:
    db = SessionLocal()
    made = []
    # 再送待ちのジョブはワーカーが next_attempt_at に自動再送する。実チェーンでは本物の tx（同じ submit の再送 → revert）になるので、実チェーンでは 30 日後にして自動再送させない
    retry_after = timedelta(minutes=10) if not get_settings().chain_enabled else timedelta(days=30)
    for kind, status, err, nxt in (
        ("ens_update", "failed", ERRORS["ens_update"], None),
        ("fund_task", "failed", ERRORS["fund_task"], None),
        ("submit", "retry", "ValueError: replacement transaction underpriced (Waiting for the 2nd automatic resend)", datetime.now(UTC) + retry_after),
    ):
        if db.query(ChainJob).filter(ChainJob.kind == kind, ChainJob.status == status, ChainJob.error.like(f"%{DEMO_TAG}%")).first():
            print(f"skip: {kind} {status} already exists")
            continue
        j = db.query(ChainJob).filter(ChainJob.kind == kind, ChainJob.status == "done").order_by(ChainJob.created_at.desc()).first()
        if j is None:
            print(f"skip: cannot create because there is no confirmed {kind} job (create one first with seed.py or via the UI)")
            continue
        j.status = status
        j.attempts = 5 if status == "failed" else 2
        j.error = f"{DEMO_TAG} {err}"
        j.next_attempt_at = nxt
        j.finished_at = None
        made.append((kind, status))
    db.commit()
    for kind, status in made:
        print(f"made: {kind} → {status}")
    counts = {s: n for s, n in db.query(ChainJob.status, func.count(ChainJob.id)).group_by(ChainJob.status).all()}
    print("chain_jobs:", counts)
    print("To revert, requeue from /ops/jobs or run: update chain_jobs set status='done', next_attempt_at=null, error=null where error like '%[demo]%'")


if __name__ == "__main__":
    main()
