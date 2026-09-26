"use client";

import type { EnsRole } from "@/lib/api";
import { Card, Mono } from "./ui";

/** FR-028: ENSv2 EAC の役割をオンチェーンから読んで表示する。verified は hasRoles の「できる / できない」の両方を確認した結果 */
export function EnsRolesTable({ roles, subregistry }: { roles: EnsRole[]; subregistry?: string | null }) {
  return (
    <Card>
      <h2 className="mb-1 font-semibold">Permissions <span className="text-xs font-normal text-neutral-500">ENSv2 Enhanced Access Control. Values are live data read from Sepolia</span></h2>
      <p className="mb-3 text-xs text-neutral-500">Owning a name and holding permissions are separate. The Reputation key can only setText on rating keys; the Project key can only register project subnames and setText on codrea.project.*. Anything else reverts.</p>
      {roles.length === 0 ? (
        <p className="text-sm text-neutral-500">Could not fetch Roles (RPC not configured, mock publish, or Namespace not set up).</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="whitespace-nowrap text-left text-neutral-500"><tr><th className="py-1 pr-3">Role</th><th className="pr-3">Account</th><th className="pr-3">Can</th><th className="pr-3">Cannot</th><th>Verification</th></tr></thead>
            <tbody>
              {roles.map((r) => (
                <tr key={r.role} className="border-t border-neutral-100 align-top [&>td]:py-1.5 [&>td]:pr-3">
                  <td className="whitespace-nowrap font-medium">{r.role}</td>
                  <td>{r.account ? <Mono className="text-neutral-900">{r.account.slice(0, 8)}…{r.account.slice(-4)}</Mono> : "-"}</td>
                  <td className="min-w-48">{r.can ?? r.error}</td>
                  <td className="min-w-40 text-neutral-600">{r.cannot ?? "-"}</td>
                  <td className="whitespace-nowrap">
                    {r.verified === undefined ? "-" : r.verified ? <span className="rounded-sm border border-neutral-900 bg-neutral-900 px-1.5 text-[10px] text-white">Verified</span> : <span className="rounded-sm border border-neutral-400 px-1.5 text-[10px] text-neutral-600">Not isolated</span>}
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
      {subregistry && <p className="mt-2 text-xs text-neutral-500">Agent Subregistry: <Mono>{subregistry}</Mono> (project-* subnames are registered here)</p>}
    </Card>
  );
}
