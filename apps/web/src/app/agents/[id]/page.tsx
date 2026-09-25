"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, CATEGORY_LABEL, short, type AgentDetail, type Review } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BackLink, Badge, Button, Card, EnsLink, HumanBadge, Mono, Stars, TxLink } from "@/components/ui";
import { PERMISSIONS } from "@/lib/mock";

export default function AgentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useAuth();
  const { data: a } = useQuery({ queryKey: ["agent", id], queryFn: () => api<AgentDetail>(`/agents/${id}`), refetchInterval: (q) => (q.state.data?.status === "publishing" ? 3000 : false) });
  const { data: reviews } = useQuery({ queryKey: ["agent-reviews", id], queryFn: () => api<Review[]>(`/agents/${id}/reviews`) });
  if (!a) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  const ensEntries = Object.entries(a.ens_records ?? {});

  return (
    <div className="space-y-6">
      <BackLink href="/">Marketplace</BackLink>
      <Card>
        <div className="flex flex-wrap items-start gap-4">
          <div className="grid h-16 w-16 shrink-0 place-items-center rounded-lg bg-neutral-900 text-xs font-bold tracking-widest text-white">AI</div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-2xl font-bold">{a.name}</h1>
              <Badge>{CATEGORY_LABEL[a.category] ?? a.category}</Badge>
              <Badge status={a.status} />
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-3 text-sm">
              {a.ens_name && <EnsLink name={a.ens_name} />}
              <TxLink hash={a.ens_tx_hash} label="ENS tx" />
              <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-sm border border-neutral-300 px-2 py-0.5 text-xs text-neutral-700">Creator {a.creator.display_name && <b>{a.creator.display_name}</b>} <Mono>{short(a.creator.wallet_address)}</Mono></span>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
              <Stars value={Number(a.rating_avg)} count={a.rating_count} />
              <span className="whitespace-nowrap tabular-nums">Fee <b>{a.fee_bps / 100}%</b></span>
              <span className="whitespace-nowrap tabular-nums">実績 <b>{a.completed_count}</b></span>
            </div>
          </div>
          {me && a.status === "published" && (
            <Link href={`/cases/new?agent=${a.id}`} className="shrink-0"><Button>この Agent に依頼する</Button></Link>
          )}
        </div>
        <p className="mt-4 whitespace-pre-wrap text-sm text-neutral-700">{a.description}</p>
      </Card>

      <div className="grid gap-6 md:grid-cols-2">
        <Card>
          <h2 className="mb-2 font-semibold">進め方・ルール</h2>
          <p className="whitespace-pre-wrap text-sm text-neutral-700">{a.rules || "（未設定）"}</p>
        </Card>
        <Card>
          <h2 className="mb-2 font-semibold">ENS レコード <span className="text-xs font-normal text-neutral-500">Sepolia の ENS から直接読み取り</span></h2>
          {ensEntries.length === 0 ? (
            <p className="text-sm text-neutral-500">{a.ens_name ? "ENS から取得できませんでした（RPC 未設定またはモック公開）。" : "未公開"}</p>
          ) : (
            <dl className="space-y-1 text-sm">
              {ensEntries.map(([k, v]) => (
                <div key={k} className="flex gap-2"><dt className="w-36 shrink-0 whitespace-nowrap font-mono text-xs text-neutral-500">{k}</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{v}</dd></div>
              ))}
            </dl>
          )}
        </Card>
      </div>

      <Card>
        <h2 className="mb-2 font-semibold">権限管理 <span className="text-xs font-normal text-neutral-500">ENSv2 EAC で「誰がどの情報を更新できるか」を制御</span></h2>
        <table className="w-full text-xs">
          <thead className="text-left text-neutral-500"><tr><th className="py-1">ロール</th><th>名前</th><th>できること</th></tr></thead>
          <tbody>{PERMISSIONS.map((p) => <tr key={p.role} className="border-t border-neutral-100 align-top"><td className="whitespace-nowrap py-1 pr-3 font-medium">{p.role}</td><td className="pr-3"><Mono className="text-neutral-900">{p.ens(a.ens_name ?? `${a.label}.choice.eth`, a.creator.display_name ?? short(a.creator.wallet_address))}</Mono></td><td>{p.can}</td></tr>)}</tbody>
        </table>
        <p className="mt-2 text-xs text-neutral-500">名前を持つことと権限を持つことは別。サービスが止まっても Agent の identity は ENS 上に残り、他のサービスから参照できます。</p>
      </Card>

      <Card>
        <h2 className="mb-3 font-semibold">Human-backed Review <span className="text-xs font-normal text-neutral-500">World で人間確認をした当事者だけが投稿できます</span></h2>
        {!reviews?.length ? <p className="text-sm text-neutral-500">まだレビューはありません</p> : (
          <ul className="divide-y divide-neutral-100">
            {reviews.map((r) => (
              <li key={r.id} className="py-3">
                <div className="flex flex-wrap items-center gap-2 text-sm"><Stars value={r.rating} /><HumanBadge /><span className="whitespace-nowrap text-xs text-neutral-500"><Mono>{short(r.reviewer.wallet_address)}</Mono> · {new Date(r.created_at).toLocaleDateString("ja-JP")}</span></div>
                <p className="mt-1 text-sm text-neutral-700">{r.comment}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
