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
    parser = argparse.ArgumentParser(description="エージェントの停止と再開（GRD-007）")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text, needs_case in (
        ("stop-all", "全体を止める（OPS-001）", False),
        ("stop-case", "案件単位で止める（OPS-002）", True),
        ("resume-all", "全体の停止を解く（OPS-003）", False),
        ("resume-case", "案件単位の停止を解く（OPS-003）", True),
    ):
        p = sub.add_parser(name, help=help_text)
        if needs_case:
            p.add_argument("case_id")
        p.add_argument("--reason", required=name.startswith("stop"), default="", help="停止・再開の理由（停止では必須）")
        p.add_argument("--operator", default=getpass.getuser(), help="操作した人（既定は OS のユーザー名）")
    sub.add_parser("status", help="いま止まっている範囲を表示する")
    args = parser.parse_args(argv)

    db = SessionLocal()
    try:
        if args.command == "status":
            rows = control.stopped_scopes(db)
            if not rows:
                print("停止中の範囲はありません")
            for r in rows:
                print(f"停止中  {r.scope}  {r.created_at:%Y-%m-%d %H:%M:%S}  {r.operator}  {r.reason}")
            return 0
        case_id = getattr(args, "case_id", None)
        if args.command.startswith("stop"):
            row = control.stop(db, case_id=case_id, reason=args.reason, operator=args.operator)
            revoked = funding_guard.revoke(db, case_id=case_id, reason=f"{row.scope} の停止: {args.reason}")
            print(f"送金操作権限を失効  {revoked} 件")
        else:
            row = control.resume(db, case_id=case_id, reason=args.reason, operator=args.operator)
        print(f"{row.action}  {row.scope}  {row.created_at:%Y-%m-%d %H:%M:%S}  {row.operator}")
        return 0
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
