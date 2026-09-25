"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Card, Empty, EnsLink, inputCls, Mono, PageTitle, TxLink } from "@/components/ui";
import { EnsRecords, useEnsResolve } from "@/components/ens-records";

type NameRow = { name: string; kind: "agent" | "reputation" | "subagent" | "project" | "person"; owner_mode: string; tx_hash: string | null; created_at: string; mock: boolean; link: string; note?: string; subregistry?: string | null };
type Names = { parent: string; count: number; names: NameRow[] };

const KIND: Record<NameRow["kind"], { label: string; who: string }> = {
  agent: { label: "PM Agent", who: "Owner 鍵（platform）/ Creator（creator）" },
  subagent: { label: "専門 Agent", who: "Owner 鍵。Agent 自身のサブレジストリに発行" },
  reputation: { label: "評価", who: "Reputation 鍵が所有。評価 3 キーだけを更新" },
  project: { label: "案件", who: "Project 鍵が ROLE_REGISTRAR で発行" },
  person: { label: "人員", who: "会社管理者のウォレットが発行" },
};

/** G2/G3: プラットフォームが ENSv2（Sepolia）に発行した名前の一覧と、任意の名前の実レコード確認。ENS 賞のデモ・監査向け */
export default function EnsPage() {
  const { config } = useAuth();
  const { data } = useQuery({ queryKey: ["ens-names"], queryFn: () => api<Names>("/ens/names"), refetchInterval: 15_000 });
  const [q, setQ] = useState("");
  const [name, setName] = useState<string | null>(null);
  const [filter, setFilter] = useState<NameRow["kind"] | "all">("all");
  const rows = (data?.names ?? []).filter((r) => filter === "all" || r.kind === filter);
  const real = rows.filter((r) => !r.mock).length;
  const wc = useEnsResolve(name);
  return (
    <div className="space-y-6">
      <PageTitle title="ENS 名前空間" sub={`${config?.ens_parent_name ?? "choice.eth"} の下に発行した名前と、Sepolia 上の実レコード。役割ごとに別の鍵・別のリゾルバで管理しています（ENSv2 EAC / Permissioned Resolver）`} />

      <Card className="space-y-2">
        <h2 className="font-semibold">名前を調べる <span className="text-xs font-normal text-neutral-500">レジストリを .eth から辿って読み取り、ENSIP-10 の resolve() でも同じ値が返るかを確認します</span></h2>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setName(q.trim().toLowerCase() || null); }}>
          <input className={inputCls} placeholder="web-pm.choice.eth" value={q} onChange={(e) => setQ(e.target.value)} />
          <button className="whitespace-nowrap rounded-md bg-neutral-900 px-4 py-2 text-sm text-white" type="submit">読む</button>
        </form>
        {name && (
          <div className="space-y-2">
            <EnsRecords name={name} title={name} />
            {wc.data?.wildcard && (
              <p className="text-xs text-neutral-600">
                ENSIP-10 <Mono>resolve(bytes,bytes)</Mono>: {wc.data.wildcard.supported ? "対応" : "非対応"}
                {wc.data.wildcard.checked_key && <> · <Mono>{wc.data.wildcard.checked_key}</Mono> = 「{wc.data.wildcard.value}」 {wc.data.wildcard.matches ? "（直読みと一致）" : "（直読みと不一致）"}</>}
              </p>
            )}
          </div>
        )}
      </Card>

      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <h2 className="font-semibold">発行した名前 <span className="text-xs font-normal tabular-nums text-neutral-500">{rows.length} 件（実機 {real} / モック {rows.length - real}）</span></h2>
          <div className="ml-auto flex flex-wrap gap-1">
            {(["all", "agent", "subagent", "reputation", "project", "person"] as const).map((k) => (
              <button key={k} onClick={() => setFilter(k)} className={`whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs ${filter === k ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-700"}`}>{k === "all" ? "すべて" : KIND[k].label}</button>
            ))}
          </div>
        </div>
        {!rows.length ? <Empty>まだ名前がありません</Empty> : (
          <Card className="overflow-x-auto p-0">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="px-3 py-2">名前</th><th className="px-3 py-2">種別</th><th className="px-3 py-2">発行・更新する鍵</th><th className="px-3 py-2">tx</th><th className="px-3 py-2">発行日時</th><th className="px-3 py-2"></th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.name} className="border-t border-neutral-100 align-middle [&>td]:px-3 [&>td]:py-1.5">
                    <td><button className="text-left" onClick={() => { setQ(r.name); setName(r.name); window.scrollTo({ top: 0, behavior: "smooth" }); }}><Mono className="text-neutral-900 underline-offset-2 hover:underline">{r.name}</Mono></button></td>
                    <td className="whitespace-nowrap"><Badge>{KIND[r.kind].label}</Badge>{r.mock && <Badge className="ml-1" status="draft">mock</Badge>}</td>
                    <td className="whitespace-nowrap text-xs text-neutral-600">{r.note ?? KIND[r.kind].who}</td>
                    <td className="whitespace-nowrap text-xs"><TxLink hash={r.tx_hash} /></td>
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{new Date(r.created_at).toLocaleString("ja-JP")}</td>
                    <td className="whitespace-nowrap text-xs"><Link href={r.link} className="text-neutral-900 underline underline-offset-2">開く</Link>{!r.mock && <span className="ml-2"><EnsLink name={r.name} /></span>}</td>
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
