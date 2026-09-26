"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Card, Empty, EnsLink, inputCls, Mono, PageTitle, TxLink } from "@/components/ui";
import { EnsRecords, useEnsResolve } from "@/components/ens-records";

type NameRow = { name: string; kind: "agent" | "reputation" | "subagent" | "project" | "person"; owner_mode: string; tx_hash: string | null; created_at: string; mock: boolean; link: string; note?: string; subregistry?: string | null };
type Names = { parent: string; count: number; names: NameRow[] };

const KIND: Record<NameRow["kind"], { label: string; who: string }> = {
  agent: { label: "PM Agent", who: "Owner key (platform) / Creator (creator)" },
  subagent: { label: "Specialist Agent", who: "Owner key. Issued in the Agent's own Subregistry" },
  reputation: { label: "Rating", who: "Owned by the Reputation key. Updates only the 3 rating keys" },
  project: { label: "Case", who: "Issued by the Project key with ROLE_REGISTRAR" },
  person: { label: "Member", who: "Issued by the Company admin's Wallet" },
};

/** G2/G3: プラットフォームが ENSv2（Sepolia）に発行した名前の一覧と、任意の名前の実レコード確認。ENS 賞のデモ・監査向け */
export default function EnsPage() {
  return <Suspense fallback={<p className="text-sm text-neutral-500">Loading…</p>}><EnsPageInner /></Suspense>;
}

function EnsPageInner() {
  const { config } = useAuth();
  const initial = useSearchParams().get("name")?.toLowerCase() ?? "";
  const { data } = useQuery({ queryKey: ["ens-names"], queryFn: () => api<Names>("/ens/names"), refetchInterval: 15_000 });
  const [q, setQ] = useState(initial);
  const [name, setName] = useState<string | null>(initial || null);
  const [filter, setFilter] = useState<NameRow["kind"] | "all">("all");
  const rows = (data?.names ?? []).filter((r) => filter === "all" || r.kind === filter);
  const real = rows.filter((r) => !r.mock).length;
  const wc = useEnsResolve(name);
  return (
    <div className="space-y-6">
      <PageTitle title="ENS Namespace" sub={`Names issued under ${config?.ens_parent_name ?? "guildace.eth"} and their live Records on Sepolia. Each Role is managed with its own key and Resolver (ENSv2 EAC / Permissioned Resolver)`} />

      <Card className="space-y-2">
        <h2 className="font-semibold">Look up a name <span className="text-xs font-normal text-neutral-500">Walks the registry down from .eth, and checks that ENSIP-10 resolve() returns the same value</span></h2>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setName(q.trim().toLowerCase() || null); }}>
          <input className={inputCls} placeholder="web-pm.guildace.eth" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="whitespace-nowrap rounded-md bg-neutral-900 px-4 py-2 text-sm text-white" type="submit">Read</button>
        </form>
        {name && (
          <div className="space-y-2">
            <EnsRecords name={name} title={name} />
            {wc.data?.resolver && (
              <p className="text-xs text-neutral-500">
                Etherscan: <a className="underline underline-offset-2" href={`https://sepolia.etherscan.io/address/${wc.data.resolver}#readContract`} target="_blank" rel="noreferrer">resolver</a>
                {wc.data.registry && <> · <a className="underline underline-offset-2" href={`https://sepolia.etherscan.io/address/${wc.data.registry}#readContract`} target="_blank" rel="noreferrer">registry</a></>}
                {wc.data.subregistry && <> · <a className="underline underline-offset-2" href={`https://sepolia.etherscan.io/address/${wc.data.subregistry}#readContract`} target="_blank" rel="noreferrer">subregistry</a></>}
              </p>
            )}
            {wc.data?.wildcard && (
              <p className="text-xs text-neutral-600">
                ENSIP-10 <Mono>resolve(bytes,bytes)</Mono>: {wc.data.wildcard.supported ? "supported" : "not supported"}
                {wc.data.wildcard.checked_key && <> · <Mono>{wc.data.wildcard.checked_key}</Mono> = &quot;{wc.data.wildcard.value}&quot; {wc.data.wildcard.matches ? "(matches direct read)" : "(differs from direct read)"}</>}
              </p>
            )}
          </div>
        )}
      </Card>

      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">Issued names <span className="text-xs font-normal tabular-nums text-neutral-500">{rows.length} (on-chain {real} / Mock {rows.length - real})</span></h2>
          <div className="ml-auto flex flex-wrap gap-1">
            {(["all", "agent", "subagent", "reputation", "project", "person"] as const).map((k) => (
              <button key={k} onClick={() => setFilter(k)} className={`whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs ${filter === k ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-700"}`}>{k === "all" ? "All" : KIND[k].label}</button>
            ))}
          </div>
        </div>
        {!rows.length ? <Empty>No names yet</Empty> : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="px-3 py-2">Name</th><th className="px-3 py-2">Type</th><th className="px-3 py-2">Key that issues / updates</th><th className="px-3 py-2">tx</th><th className="px-3 py-2">Issued at</th><th className="px-3 py-2"></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className="border-t border-neutral-100 align-middle [&>td]:px-3 [&>td]:py-1.5">
                    <td><button className="text-left" onClick={() => { setQ(r.name); setName(r.name); window.scrollTo({ top: 0, behavior: "smooth" }); }}><Mono className="text-neutral-900 underline-offset-2 hover:underline">{r.name}</Mono></button></td>
                    <td className="whitespace-nowrap"><Badge>{KIND[r.kind].label}</Badge>{r.mock && <Badge className="ml-1" status="draft">mock</Badge>}</td>
                    <td className="whitespace-nowrap text-xs text-neutral-600">{r.note ?? KIND[r.kind].who}</td>
                    <td className="whitespace-nowrap text-xs"><TxLink hash={r.tx_hash} /></td>
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{new Date(r.created_at).toLocaleString("en-US")}</td>
                    <td className="whitespace-nowrap text-xs"><Link href={r.link} className="text-neutral-900 underline underline-offset-2">Open</Link>{!r.mock && <span className="ml-2"><EnsLink name={r.name} /></span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        )}
      </div>
    </div>
  );
}
