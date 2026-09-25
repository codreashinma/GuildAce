"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, short, usdc, type Dispute } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Markdown } from "@/components/markdown";
import { WorldVerifyButton } from "@/components/world-verify";
import { BackLink, Card, ErrorBox, HumanBadge, TxLink } from "@/components/ui";

export default function DisputePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data: d } = useQuery({ queryKey: ["dispute", id], queryFn: () => api<Dispute>(`/disputes/${id}`), refetchInterval: 3000 });
  const [err, setErr] = useState<unknown>(null);
  const [open, setOpen] = useState<string | null>(null);
  if (!d) return <p className="text-sm text-slate-500">読み込み中…</p>;
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
      <BackLink href="/jury">Jury 一覧</BackLink>
      <Card>
        <h1 className="text-xl font-bold">⚖️ {c.title}</h1>
        <p className="mt-1 text-sm text-slate-500">発注者 {short(c.client.wallet_address)} vs PM Agent <Link className="text-blue-700" href={`/agents/${c.agent.id}`}>{c.agent.name}</Link> · Escrow 保留額 <b>{usdc(c.budget)} USDC</b> · <Link className="text-blue-700 underline" href={`/cases/${c.id}`}>案件詳細</Link></p>
        <div className="mt-3 rounded-lg bg-rose-50 p-3 text-sm"><b>差し戻し理由（発注者）:</b> {d.reason}</div>
      </Card>

      <Card>
        <h2 className="font-semibold">論点サマリー <span className="text-xs font-normal text-slate-500">AI が整理。判断はしません</span></h2>
        {!s ? <p className="mt-2 animate-pulse text-sm">🤖 論点を整理しています…</p> : s.error ? <ErrorBox error={s.error} /> : (
          <div className="mt-2 grid gap-4 text-sm md:grid-cols-2">
            <div><h3 className="font-medium">争点</h3><ul className="list-disc pl-5">{s.issues?.map((i) => <li key={i}>{i}</li>)}</ul></div>
            <div><h3 className="font-medium">確認すべき事実</h3><ul className="list-disc pl-5">{s.facts_to_check?.map((i) => <li key={i}>{i}</li>)}</ul></div>
            <div className="rounded-lg bg-slate-50 p-3"><h3 className="font-medium">発注者の主張</h3><p>{s.client_position}</p></div>
            <div className="rounded-lg bg-slate-50 p-3"><h3 className="font-medium">Agent 側の主張</h3><p>{s.agent_position}</p></div>
            {s.ai_note && <p className="text-xs text-slate-500 md:col-span-2">AI の参考所見: {s.ai_note}</p>}
          </div>
        )}
      </Card>

      <Card>
        <h2 className="font-semibold">成果物</h2>
        <div className="mt-2 space-y-1">
          {c.tasks.map((t) => (
            <div key={t.id}>
              <button className="text-sm text-blue-700 hover:underline" onClick={() => setOpen(open === t.id ? null : t.id)}>{t.type === "human" ? "🧑" : "🤖"} {t.title} {open === t.id ? "▲" : "▼"}</button>
              {open === t.id && <div className="mt-1 rounded-lg bg-slate-50 p-3"><Markdown>{t.deliverable ?? "（なし）"}</Markdown></div>}
            </div>
          ))}
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold">投票 <span className="text-sm font-normal text-slate-500">{d.votes.length}/{d.required_votes} · 支払い {counts.release} / 返金 {counts.refund}</span></h2>
        <ul className="mt-2 space-y-1 text-sm">
          {d.votes.map((v) => <li key={v.id} className="flex items-center gap-2"><HumanBadge /><span>{short(v.voter.wallet_address)}</span><span className={v.vote === "release" ? "text-emerald-700" : "text-rose-700"}>{v.vote === "release" ? "支払い" : "返金"}</span></li>)}
        </ul>
        {d.status === "closed" ? (
          <div className="mt-3 rounded-lg bg-teal-50 p-3 text-sm">結果: <b>{d.outcome === "release" ? "支払い（配分どおり）" : "全額返金"}</b> — Escrow の resolve を実行しました。 <TxLink hash={d.resolve_tx_hash} label="resolve tx" /></div>
        ) : !me ? <p className="mt-3 text-sm text-slate-500">投票するには Sign in してください。</p>
          : isParty ? <p className="mt-3 text-sm text-slate-500">当事者は投票できません。</p>
          : voted ? <p className="mt-3 text-sm text-emerald-700">投票済みです。残りの投票を待っています。</p>
          : (
            <div className="mt-3 space-y-2">
              <p className="text-sm">World で人間であることを確認したうえで投票します。1 人 1 票。3 票そろった時点で多数決が Escrow に反映されます。</p>
              <div className="flex flex-wrap gap-2">
                <WorldVerifyButton action="jury" signal={d.id} label="支払いに投票" onVerified={(p) => vote("release", p)} />
                <WorldVerifyButton action="jury" signal={d.id} label="返金に投票" variant="danger" onVerified={(p) => vote("refund", p)} />
              </div>
              <ErrorBox error={err} />
            </div>
          )}
      </Card>
    </div>
  );
}
