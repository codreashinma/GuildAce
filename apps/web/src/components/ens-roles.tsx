"use client";

import type { EnsRole } from "@/lib/api";
import { Card, Mono } from "./ui";

/** FR-028: ENSv2 EAC の役割をオンチェーンから読んで表示する。verified は hasRoles の「できる / できない」の両方を確認した結果 */
export function EnsRolesTable({ roles, subregistry }: { roles: EnsRole[]; subregistry?: string | null }) {
  return (
    <Card>
      <h2 className="mb-1 font-semibold">権限管理 <span className="text-xs font-normal text-neutral-500">ENSv2 Enhanced Access Control。値は Sepolia から読んだ実データ</span></h2>
      <p className="mb-3 text-xs text-neutral-500">名前を持つことと権限を持つことは別。Reputation 鍵は評価キーの setText だけ、Project 鍵は project subname の register と codrea.project.* の setText だけができ、それ以外は revert します。</p>
      {roles.length === 0 ? (
        <p className="text-sm text-neutral-500">役割を取得できませんでした（RPC 未設定、モック公開、または Creator 所有の名前）。</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="whitespace-nowrap text-left text-neutral-500"><tr><th className="py-1 pr-3">ロール</th><th className="pr-3">アカウント</th><th className="pr-3">できること</th><th className="pr-3">できないこと</th><th>検証</th></tr></thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.role} className="border-t border-neutral-100 align-top [&>td]:py-1.5 [&>td]:pr-3">
                  <td className="whitespace-nowrap font-medium">{r.role}</td>
                  <td>{r.account ? <Mono className="text-neutral-900">{r.account.slice(0, 8)}…{r.account.slice(-4)}</Mono> : "-"}</td>
                  <td className="min-w-48">{r.can ?? r.error}</td>
                  <td className="min-w-40 text-neutral-600">{r.cannot ?? "-"}</td>
                  <td className="whitespace-nowrap">
                    {r.verified === undefined ? "-" : r.verified ? <span className="rounded-sm border border-neutral-900 bg-neutral-900 px-1.5 text-[10px] text-white">確認済</span> : <span className="rounded-sm border border-neutral-400 px-1.5 text-[10px] text-neutral-600">未分離</span>}
                    {r.checks && (
                      <ul className="mt-1 space-y-0.5 font-mono text-[10px] text-neutral-500">
                        {Object.entries(r.checks).map(([k, v]) => <li key={k}>{k}: {v === null ? "?" : v ? "true" : "false"}</li>)}
                      </ul>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {subregistry && <p className="mt-2 text-xs text-neutral-500">Agent のサブレジストリ: <Mono>{subregistry}</Mono>（project-* subname はここに登録される）</p>}
    </Card>
  );
}
