"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, short, usdc, type AuditEvent, type CaseAudit } from "@/lib/api";
import { BackLink, Badge, Card, EnsLink, Mono, PageTitle, TxLink } from "@/components/ui";

const ROLE: Record<string, string> = {
  client: "Client", approver: "Approver", payee: "Payee", worker: "Chain worker (server key)", "project-key": "Project key", "owner-key": "Owner key", creator: "Creator", jury: "Jury",
};
const JOB_STATUS: Record<string, string> = { done: "Confirmed", recorded: "Confirmed", queued: "Queued", running: "Sending", retry: "Retry pending", failed: "Failed", open: "Under review", closed: "Ruled" };

/** G2: 監査ビュー。案件の tx（openCase / fund / submit / approve / pay / dispute / resolve）と ENS 発行を時系列に並べ、
 *  関わったアドレスをプラットフォームが発行した ENS 名で示す（GET /cases/{id}/audit）。認証不要・第三者向け */
export default function CaseAuditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: a, error } = useQuery({ queryKey: ["case-audit", id], queryFn: () => api<CaseAudit>(`/cases/${id}/audit`), refetchInterval: 8000 });
  if (error) return <p className="text-sm text-neutral-700">Loading failed: {(error as Error).message}</p>;
  if (!a) return <p className="text-sm text-neutral-500">Loading…</p>;
  const name = (addr: string | null) => {
    if (!addr) return null;
    const hit = a.actors[addr.toLowerCase()];
    return hit?.name ? <span className="inline-flex items-center gap-1" title={addr}><EnsLink name={hit.name} />{!hit.verified && <span className="text-[10px] text-neutral-400">(not written)</span>}</span> : <span title={addr}><Mono>{short(addr)}</Mono></span>;
  };
  return (
    <div className="space-y-6">
      <BackLink href={`/cases/${id}`}>Back to case</BackLink>
      <PageTitle title="Audit view" sub="On-chain transactions and ENS issuances for this case, in chronological order. The source of truth for funds is the Escrow contract, and for names it is ENS (Sepolia). Signatures and World ID nullifiers are not shown." />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{a.title}</h2><Badge status={a.status} /></div>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs text-neutral-600 sm:grid-cols-[auto_1fr]">
              <dt className="whitespace-nowrap">Escrow case</dt><dd><Mono className="text-neutral-900">{a.escrow_case_id}</Mono></dd>
              <dt className="whitespace-nowrap">PM Agent (ENS)</dt><dd>{a.agent_ens_name ? <EnsLink name={a.agent_ens_name} /> : <span className="text-neutral-400">Not published</span>}</dd>
              <dt className="whitespace-nowrap">Case subname</dt><dd>{a.project_ens_name ? <EnsLink name={a.project_ens_name} /> : <span className="text-neutral-400">Not issued</span>}</dd>
              <dt className="whitespace-nowrap">Approvers / Required</dt>
              <dd className="flex flex-wrap items-center gap-2"><span className="tabular-nums">{a.approvers.length} / {a.threshold}</span>{a.approvers.map((ap) => <span key={ap}>{name(ap)}</span>)}</dd>
            </dl>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-right text-xs text-neutral-500 sm:grid-cols-4">
            <Stat label="Events" value={a.counts.events} /><Stat label="On-chain tx" value={a.counts.onchain} /><Stat label="Failed" value={a.counts.failed} /><Stat label="Shown by ENS name" value={a.counts.named_actors} />
          </div>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold">Involved addresses <span className="text-xs font-normal text-neutral-500">ENS reverse lookup (same rules as GET /ens/reverse; resolved from Member, Agent payout, and Company admin names)</span></h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">ENS name</th><th className="pr-3">Address</th><th>Role</th></tr></thead>
            <tbody>
              {Object.values(a.actors).map((x) => (
                <tr key={x.address} className="border-t border-neutral-100 [&>td]:py-2 [&>td]:pr-3">
                  <td>{x.name ? <span className="inline-flex items-center gap-1"><EnsLink name={x.name} />{!x.verified && <span className="text-[10px] text-neutral-400">(not written)</span>}</span> : <span className="text-neutral-400">No name</span>}</td>
                  <td><Mono>{x.address}</Mono></td>
                  <td className="flex flex-wrap gap-1">{x.roles.map((r) => <Badge key={r}>{ROLE[r] ?? r}</Badge>)}</td>
                </tr>
              ))}
              {Object.keys(a.actors).length === 0 && <tr><td colSpan={3} className="py-3 text-neutral-400">None yet</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold">Timeline <span className="text-xs font-normal text-neutral-500">Worker transactions come from chain_jobs (idempotency key, retries); openCase is recorded after verifying the Client&apos;s tx</span></h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">#</th><th className="pr-3">Time</th><th className="pr-3">Event</th><th className="pr-3">Task</th><th className="pr-3">Actor</th><th className="pr-3">tx</th><th>Status</th></tr></thead>
            <tbody>
              {a.events.map((e) => (
                <tr key={e.seq} className="border-t border-neutral-100 align-top [&>td]:py-2 [&>td]:pr-3">
                  <td className="tabular-nums text-neutral-500">{e.seq}</td>
                  <td className="whitespace-nowrap tabular-nums text-xs text-neutral-500">{e.at ? new Date(e.at).toLocaleString("en-US") : "—"}</td>
                  <td><div>{e.label}</div><Detail e={e} name={name} /></td>
                  <td className="min-w-32 text-xs">{e.task_title ?? <span className="text-neutral-400">Entire case</span>}</td>
                  <td className="text-xs"><div className="text-neutral-500">{ROLE[e.actor_role] ?? e.actor_role}</div>{e.actor && <div>{name(e.actor)}</div>}</td>
                  <td>{e.tx_hash ? <TxLink hash={e.tx_hash} label={e.mock ? "mock" : "tx"} /> : <span className="text-xs text-neutral-400">—</span>}</td>
                  <td><Badge status={e.status === "failed" ? "publish_failed" : e.status === "done" || e.status === "recorded" ? "done" : undefined}>{JOB_STATUS[e.status] ?? e.status}</Badge></td>
                </tr>
              ))}
              {a.events.length === 0 && <tr><td colSpan={7} className="py-3 text-neutral-400">No on-chain records yet</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-neutral-500">You can check Escrow deposits and payouts via the Etherscan tx links, and the actual name records via <Link className="underline" href="/ens">/ens</Link>, directly at their sources of truth.</p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div><div className="text-lg font-semibold tabular-nums text-neutral-900">{value}</div><div className="whitespace-nowrap">{label}</div></div>;
}

function Detail({ e, name }: { e: AuditEvent; name: (a: string | null) => React.ReactNode }) {
  const d = e.detail;
  const items: React.ReactNode[] = [];
  if (typeof d.amount === "string") items.push(<span key="amt" className="whitespace-nowrap">Amount {usdc(d.amount)} USDC</span>);
  if (typeof d.pay_amount === "string") items.push(<span key="pay" className="whitespace-nowrap">Released {usdc(d.pay_amount)} / Refunded {usdc(String(d.refund_amount ?? "0"))} USDC</span>);
  if (typeof d.approval_count === "number") items.push(<span key="cnt" className="whitespace-nowrap tabular-nums">Approvals {d.approval_count} / {String(d.threshold ?? "?")}</span>);
  if (typeof d.deliverable_hash === "string") items.push(<span key="h" className="whitespace-nowrap">Deliverable <Mono>{short(d.deliverable_hash)}</Mono></span>);
  if (typeof d.payee === "string") items.push(<span key="p" className="whitespace-nowrap">Payee {name(d.payee)}</span>);
  if (typeof d.ens_name === "string") items.push(<span key="e"><EnsLink name={d.ens_name} /></span>);
  if (Array.isArray(d.voters)) items.push(<span key="v" className="flex flex-wrap gap-1">Votes {d.voters.map((v) => <span key={String(v)}>{name(String(v))}</span>)}</span>);
  if (typeof d.outcome === "string") items.push(<span key="o">Outcome {d.outcome === "release" ? "Release" : "Refund"}</span>);
  if (typeof d.error === "string") items.push(<span key="err" className="text-neutral-700">Error: <Mono>{d.error}</Mono></span>);
  if (items.length === 0) return null;
  return <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-neutral-600">{items}</div>;
}
