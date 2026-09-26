"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, short, usdc, type Dispute, type DisputeSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Markdown } from "@/components/markdown";
import { WorldVerifyButton } from "@/components/world-verify";
import { AddrName } from "@/components/addr-name";
import { Amount, BackLink, Card, ErrorBox, HumanBadge, KindTag, Mono, TxLink } from "@/components/ui";

export default function DisputePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data: d } = useQuery({ queryKey: ["dispute", id], queryFn: () => api<Dispute>(`/disputes/${id}`), refetchInterval: 3000 });
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!d) return <p className="text-sm text-neutral-500">Loading…</p>;
  const s = d.summary_json;
  const c = d.case;
  const voted = me && d.votes.some((v) => v.voter.id === me.id);
  const isParty = me && (c.client.id === me.id || c.agent.creator_id === me.id || c.tasks.some((t) => t.human_task?.worker?.id === me.id));
  const counts = { release: d.votes.filter((v) => v.vote === "release").length, refund: d.votes.filter((v) => v.vote === "refund").length };
  const vote = async (v: "release" | "refund", p: unknown) => {
    setErr(null);
    try { await api(`/disputes/${d.id}/vote`, { method: "POST", json: { vote: v, idkit_response: p } }); qc.invalidateQueries({ queryKey: ["dispute", id] }); } catch (e) { setErr(e); throw e; }
  };

  return (
    <div className="space-y-4">
      <BackLink href="/jury">Jury list</BackLink>
      <Card>
        <h1 className="text-xl font-bold">{c.title}</h1>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-neutral-500"><span className="whitespace-nowrap">Client <Mono>{short(c.client.wallet_address)}</Mono></span><span className="whitespace-nowrap">PM Agent <Link className="text-neutral-900 underline underline-offset-2" href={`/agents/${c.agent.id}`}>{c.agent.name}</Link></span><span className="whitespace-nowrap">Held in Escrow <Amount value={usdc(c.budget)} className="font-semibold text-neutral-900" /></span><Link className="whitespace-nowrap text-neutral-900 underline underline-offset-2" href={`/cases/${c.id}`}>Case details</Link></p>
        <div className="mt-3 rounded-md border-l-2 border-neutral-900 bg-neutral-100 p-3 text-sm"><b>Reason for sending back (Client):</b> {d.reason}</div>
      </Card>

      <Card>
        <h2 className="font-semibold">Issue summary <span className="text-xs font-normal text-neutral-500">Organized by AI. AI does not make the decision</span></h2>
        <SummaryBody s={s} />
      </Card>

      <Card>
        <h2 className="font-semibold">Deliverables</h2>
        <div className="mt-2 space-y-1">
          {c.tasks.map((t) => (
            <div key={t.id}>
              <button className="inline-flex items-center gap-2 text-left text-sm text-neutral-900 hover:underline" onClick={() => setOpen(open === t.id ? null : t.id)}><KindTag kind={t.type} /><span>{t.title}</span><span className="text-xs text-neutral-400">{open === t.id ? "▲" : "▼"}</span></button>
              {open === t.id && <div className="mt-1 rounded-md border border-neutral-200 p-3"><Markdown>{t.deliverable ?? "(none)"}</Markdown></div>}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="flex flex-wrap items-baseline gap-x-3 font-semibold">Votes <span className="whitespace-nowrap text-sm font-normal tabular-nums text-neutral-500">{d.votes.length}/{d.required_votes}</span><span className="whitespace-nowrap text-sm font-normal tabular-nums text-neutral-500">Payment {counts.release} / Refund {counts.refund}</span></h2>
        <ul className="mt-2 space-y-1 text-sm">
          {d.votes.map((v) => <li key={v.id} className="flex flex-wrap items-center gap-2"><HumanBadge /><AddrName address={v.voter.wallet_address} /><span className="whitespace-nowrap rounded-sm border border-neutral-900 px-1.5 text-xs">{v.vote === "release" ? "Payment" : "Refund"}</span></li>)}
        </ul>
        {d.status === "closed" ? (
          <div className="mt-3 rounded-md border border-neutral-900 p-3 text-sm">Outcome: <b>{d.outcome === "release" ? "Payment (to each step's payee)" : "Full refund"}</b>. The chain worker sent Escrow resolve for each step. <TxLink hash={d.resolve_tx_hash} label="resolve tx" /></div>
        ) : !me ? <p className="mt-3 text-sm text-neutral-500">Please sign in to vote.</p>
          : isParty ? <p className="mt-3 text-sm text-neutral-500">Parties to the case cannot vote.</p>
          : voted ? <p className="mt-3 text-sm text-neutral-900">You have voted. Waiting for the remaining votes.</p>
          : (
            <div className="mt-3 space-y-2">
              <p className="text-sm">Verify that you are human with World, then vote. One person, one vote. Once 3 votes are in, the majority decision is applied to Escrow.</p>
              <div className="flex flex-wrap gap-2">
                <WorldVerifyButton action="jury" signal={d.id} label="Vote for payment" onVerified={(p) => vote("release", p)} />
                <WorldVerifyButton action="jury" signal={d.id} label="Vote for refund" variant="danger" onVerified={(p) => vote("refund", p)} />
              </div>
              <ErrorBox error={err} />
            </div>
          )}
      </Card>
    </div>
  );
}

/** 論点整理がまだ終わっていない（投票で resolve_jobs だけが入った場合も含む） */
function pending(s: DisputeSummary | null): boolean {
  return !s || (s.source !== "agents" && !s.issues && !s.error);
}

function SummaryBody({ s }: { s: DisputeSummary | null }) {
  if (!s || pending(s)) return <p className="mt-2 animate-pulse text-sm">Summarizing the issues…</p>;
  if (s.source === "agents") {
    // HIL-004: 争点ごとに双方の立場と根拠の参照を並べる。論点なしでも投票はできる
    if (s.no_issues) return <p className="mt-2 text-sm text-neutral-700">Could not summarize the issues. Please decide based on the reason for sending back and the deliverables.</p>;
    return (
      <ol className="mt-2 space-y-3 text-sm">
        {s.issues.map((i, n) => (
          <li key={n} className="rounded-md border border-neutral-200 p-3">
            <h3 className="font-medium">Issue {n + 1}: {i.title}</h3>
            <div className="mt-2 grid gap-3 md:grid-cols-2">
              <div><h4 className="text-xs font-medium text-neutral-500">Client&apos;s position</h4><p>{i.requester_position}</p></div>
              <div><h4 className="text-xs font-medium text-neutral-500">Assignee&apos;s position</h4><p>{i.provider_position}</p></div>
            </div>
            {i.evidence_refs.length > 0 && (
              <div className="mt-2"><h4 className="text-xs font-medium text-neutral-500">Evidence references</h4>
                <ul className="flex flex-wrap gap-2">{i.evidence_refs.map((r) => <li key={r} className="whitespace-nowrap rounded-sm border border-neutral-300 px-2 py-0.5 text-xs">{s.ref_labels[r] ?? r}</li>)}</ul>
              </div>
            )}
          </li>
        ))}
      </ol>
    );
  }
  if (s.error) return <ErrorBox error={s.error} />;
  return (
    <div className="mt-2 grid gap-4 text-sm md:grid-cols-2">
      <div><h3 className="font-medium">Issues</h3><ul className="list-disc pl-5">{s.issues?.map((i) => <li key={i}>{i}</li>)}</ul></div>
      <div><h3 className="font-medium">Facts to check</h3><ul className="list-disc pl-5">{s.facts_to_check?.map((i) => <li key={i}>{i}</li>)}</ul></div>
      <div className="rounded-md border border-neutral-200 p-3"><h3 className="font-medium">Client&apos;s claim</h3><p>{s.client_position}</p></div>
      <div className="rounded-md border border-neutral-200 p-3"><h3 className="font-medium">Agent&apos;s claim</h3><p>{s.agent_position}</p></div>
      {s.ai_note && <p className="text-xs text-neutral-500 md:col-span-2">AI note (for reference): {s.ai_note}</p>}
    </div>
  );
}
