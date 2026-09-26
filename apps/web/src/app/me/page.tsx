"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, short, usdc, type MeSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Card, Empty, EnsLink, HumanBadge, Mono, PageTitle, Stars, TxLink } from "@/components/ui";

const KIND: Record<string, string> = { person: "Company Member", "agent-payout": "Agent payout", "company-admin": "Company admin" };
const ROLE: Record<string, string> = { pm: "PM fee", human: "Human Task", ai: "AI Step" };

/** A4: マイページ。自分のウォレット・ENS 名・World で人間確認した行為・所属会社・作成した Agent・関わった案件・受取履歴（GET /me/summary） */
export default function MePage() {
  const { me, dev, config } = useAuth();
  const { data: s, error } = useQuery({ queryKey: ["me-summary", me?.id], queryFn: () => api<MeSummary>("/me/summary"), enabled: !!me, refetchInterval: 8000 });
  if (!me) return <p className="text-sm text-neutral-500">Please sign in.</p>;
  if (error) return <p className="text-sm text-neutral-700">Loading failed: {(error as Error).message}</p>;
  if (!s) return <p className="text-sm text-neutral-500">Loading…</p>;
  const total = s.cases.as_client + s.cases.as_approver + s.cases.as_worker + s.cases.as_jury;
  return (
    <div className="space-y-6">
      <PageTitle title="My Page" sub="Names, actions, affiliations and payouts linked to this Wallet. ENS names were issued by the platform on Sepolia; World ID actions were recorded after verifying the proof." />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{s.primary_ens ? <EnsLink name={s.primary_ens.name} /> : s.user.display_name ?? short(s.user.wallet_address)}</h2>
              {s.world_actions.length > 0 && <HumanBadge />}
              {dev && <Badge>Demo login (no key)</Badge>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-neutral-500">
              <span className="whitespace-nowrap">Wallet <Mono className="text-neutral-900">{s.user.wallet_address}</Mono></span>
              {s.user.display_name && <span className="whitespace-nowrap">Display name {s.user.display_name}</span>}
              <span className="whitespace-nowrap">Registered {new Date(s.user.created_at).toLocaleDateString("en-US")}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-right text-xs text-neutral-500 sm:grid-cols-4">
            <Stat label="Client" value={s.cases.as_client} /><Stat label="Approver" value={s.cases.as_approver} /><Stat label="Human Task" value={s.cases.as_worker} /><Stat label="Jury Vote" value={s.cases.as_jury} />
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="font-semibold">ENS Names <span className="text-xs font-normal text-neutral-500">Names issued under {config?.ens_parent_name ?? "guildace.eth"} or a Company&apos;s / Creator&apos;s .eth</span></h2>
          {s.ens_names.length === 0 ? <p className="mt-3 text-sm text-neutral-500">None yet. You get a name when you are registered as a Company Member or set your address as an Agent&apos;s payout address.</p> : (
            <ul className="mt-3 space-y-2">
              {s.ens_names.map((n) => (
                <li key={n.name} className="flex flex-wrap items-center gap-2 text-sm">
                  <EnsLink name={n.name} /><Badge status={n.verified ? "published" : undefined}>{KIND[n.kind] ?? n.kind}</Badge>
                  {!n.verified && <span className="text-xs text-neutral-400">(not written)</span>}
                  {n.tx_hash && <TxLink hash={n.tx_hash} label="tx" />}
                  {n.note && <span className="text-xs text-neutral-500">{n.note}</span>}
                  <Link href={n.link} className="text-xs text-neutral-500 underline underline-offset-2 hover:text-neutral-900">Open</Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="font-semibold">Actions with World ID Human verification <span className="text-xs font-normal text-neutral-500">Count per action. Nullifiers are not shown</span></h2>
          {s.world_actions.length === 0 ? <p className="mt-3 text-sm text-neutral-500">None yet. Recorded when you verify with World to start a Request, Approve, review, cast a Jury Vote, or Accept a Human Task.</p> : (
            <ul className="mt-3 divide-y divide-neutral-100 text-sm">
              {s.world_actions.map((w) => (
                <li key={w.action} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex items-center gap-2"><HumanBadge />{w.label} <Mono>{w.action}</Mono></span>
                  <span className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{w.count} times{w.last_at && ` · last ${new Date(w.last_at).toLocaleString("en-US")}`}</span>
                </li>
              ))}
            </ul>
          )}
          {s.reviews_received.count > 0 && <p className="mt-3 flex items-center gap-2 text-sm">Rating as a person <Stars value={s.reviews_received.avg ?? 0} count={s.reviews_received.count} /></p>}
        </Card>

        <Card>
          <h2 className="font-semibold">Companies</h2>
          {s.companies.length === 0 ? <p className="mt-3 text-sm text-neutral-500">You don&apos;t belong to any Company. You can register from <Link href="/companies" className="underline">Companies & Members</Link>.</p> : (
            <ul className="mt-3 space-y-2 text-sm">
              {s.companies.map((c, i) => (
                <li key={`${c.id}-${i}`} className="flex flex-wrap items-center gap-2">
                  <Link href="/companies" className="font-medium underline-offset-2 hover:underline">{c.name}</Link><EnsLink name={c.ens_name} />
                  <Badge status={c.relation === "admin" ? "published" : undefined}>{c.relation === "admin" ? "Admin" : "Member"}</Badge>
                  {c.member_ens && <span className="text-xs text-neutral-500">as <Mono className="text-neutral-900">{c.member_ens}</Mono></span>}
                  {c.available === false && <span className="text-xs text-neutral-400">Unavailable</span>}
                  {!c.ens_verified && <span className="text-xs text-neutral-400">(Owner not verified)</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="font-semibold">PM Agents I created</h2>
          {s.agents.length === 0 ? <p className="mt-3 text-sm text-neutral-500">None yet. You can create a <Link href="/agents/new" className="underline">new PM Agent</Link>.</p> : (
            <ul className="mt-3 space-y-2 text-sm">
              {s.agents.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/agents/${a.id}`} className="font-medium underline-offset-2 hover:underline">{a.name}</Link><Badge status={a.status} />
                  {a.ens_name && <EnsLink name={a.ens_name} />}{a.owner_mode === "creator" && <Badge>Creator-owned</Badge>}
                  <span className="whitespace-nowrap text-xs tabular-nums text-neutral-500">★{Number(a.rating_avg).toFixed(1)} ({a.rating_count}) · Completed {a.completed_count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Payout history <span className="text-xs font-normal text-neutral-500">Steps the Escrow paid to your address (as Payee of PM fees, Human Tasks, AI Steps)</span></h2>
          <div className="whitespace-nowrap text-sm">Total <Amount value={usdc(s.earnings_total)} /></div>
        </div>
        {s.earnings.length === 0 ? <div className="mt-3"><Empty>No payouts yet{total === 0 && ". Once you take part in a Case, Payments will appear here"}</Empty></div> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">Date</th><th className="pr-3">Case</th><th className="pr-3">Step</th><th className="pr-3">Type</th><th className="pr-3 text-right">Amount</th><th className="pr-3">Status</th><th>tx</th></tr></thead>
              <tbody>
                {s.earnings.map((e) => (
                  <tr key={e.task_id} className="border-t border-neutral-100 [&>td]:py-2 [&>td]:pr-3">
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{e.at ? new Date(e.at).toLocaleString("en-US") : "—"}</td>
                    <td className="min-w-40"><Link href={`/cases/${e.case_id}`} className="underline-offset-2 hover:underline">{e.case_title}</Link></td>
                    <td className="min-w-32">{e.task_title}</td>
                    <td><Badge>{ROLE[e.role] ?? e.role}</Badge></td>
                    <td className="whitespace-nowrap text-right tabular-nums">{usdc(e.amount)}</td>
                    <td><Badge status={`chain:${e.chain_status}`} /></td>
                    <td><TxLink hash={e.tx_hash} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-neutral-500">Resolved Steps were released or refunded by the Jury&apos;s decision. Amounts are what was deposited into Escrow for each Step; the total includes paid Steps only.</p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div><div className="text-lg font-semibold tabular-nums text-neutral-900">{value}</div><div className="whitespace-nowrap">{label}</div></div>;
}
