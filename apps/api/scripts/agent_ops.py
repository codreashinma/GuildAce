"""エージェントの停止と再開（WP-007 / GRD-007・運用手順書 OPS-001〜003）。管理経路として使い、公開 API には出さない（DEC-010）。
使い方（apps/api で実行。DATABASE_URL は .env または環境変数で与える）:
  .venv/bin/python scripts/agent_ops.py stop-all --reason "原因不明の送金が続いている"      # OPS-001
  .venv/bin/python scripts/agent_ops.py stop-case <案件 ID> --reason "この案件だけおかしい"    # OPS-002
  .venv/bin/python scripts/agent_ops.py resume-all --reason "原因を取り除いた"               # OPS-003
  .venv/bin/python scripts/agent_ops.py resume-case <案件 ID> --reason "原因を取り除いた"    # OPS-003
  .venv/bin/python scripts/agent_ops.py status
停止（stop-all / stop-case）は、同時に対象の送金操作権限を失効させる（OPS-001 / OPS-002 の手順 3。GRD-010）。
再開しても権限は戻らない。送金を続けるには権限を発行し直す（発行は /opened の承諾の確認のあと。WP-021）。
すでにチェーンへ送った tx は取り消せない。止まるのは「これ以上増やさない」ことだけ。"""

import argparse
import getpass
import sys

sys.path.insert(0, __file__.rsplit("/", 2)[0])
from app.agents import control, funding_guard  # noqa: E402
from app.db import SessionLocal  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Stop and resume agents (GRD-007)")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, needs_case in (
        ("stop-all", "Stop everything (OPS-001)", False),
        ("stop-case", "Stop a single case (OPS-002)", True),
        ("resume-all", "Lift the global stop (OPS-003)", False),
        ("resume-case", "Lift the stop for a case (OPS-003)", True),
    ):
        p = sub.add_parser(name, help=help_text)
        if needs_case:
            p.add_argument("case_id")
        p.add_argument("--reason", required=name.startswith("stop"), default="", help="Reason for stopping/resuming (required when stopping)")
        p.add_argument("--operator", default=getpass.getuser(), help="Operator (default: OS user name)")
    sub.add_parser("status", help="Show the scopes that are currently stopped")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "status":
            rows = control.stopped_scopes(db)
            if not rows:
                print("No scopes are stopped")
            for r in rows:
                print(f"stopped  {r.scope}  {r.created_at:%Y-%m-%d %H:%M:%S}  {r.operator}  {r.reason}")
            return 0
        case_id = getattr(args, "case_id", None)
        if args.command.startswith("stop"):
            row = control.stop(db, case_id=case_id, reason=args.reason, operator=args.operator)
            revoked = funding_guard.revoke(db, case_id=case_id, reason=f"{row.scope} stopped: {args.reason}")
            print(f"Revoked transfer permissions  {revoked}")
        else:
            row = control.resume(db, case_id=case_id, reason=args.reason, operator=args.operator)
        print(f"{row.action}  {row.scope}  {row.created_at:%Y-%m-%d %H:%M:%S}  {row.operator}")
        return 0
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
