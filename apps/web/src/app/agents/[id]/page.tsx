"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, CATEGORY_LABEL, short, type AgentDetail, type Review } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { BackLink, Badge, Button, Card, EnsLink, HumanBadge, Mono, Stars, Tag, TxLink } from "@/components/ui";
import { EnsRolesTable } from "@/components/ens-roles";

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
            <>
              <div className="mb-1 font-mono text-xs text-neutral-900">{a.ens_name}</div>
              <dl className="space-y-1 text-sm">
                {ensEntries.map(([k, v]) => (
                  <div key={k} className="grid grid-cols-[11rem_1fr] gap-2"><dt className="truncate font-mono text-xs leading-5 text-neutral-500" title={k}>{k}</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{v}</dd></div>
                ))}
              </dl>
              {a.ens_reputation_name && (
                <>
                  <div className="mb-1 mt-4 font-mono text-xs text-neutral-900">{a.ens_reputation_name} <span className="font-sans text-neutral-500">（Reputation 鍵のみ更新可）</span></div>
                  <dl className="space-y-1 text-sm">
                    {Object.entries(a.ens_reputation_records).map(([k, v]) => (
                      <div key={k} className="grid grid-cols-[11rem_1fr] gap-2"><dt className="truncate font-mono text-xs leading-5 text-neutral-500" title={k}>{k}</dt><dd className="tabular-nums">{v}</dd></div>
                    ))}
                    {Object.keys(a.ens_reputation_records).length === 0 && <dd className="text-xs text-neutral-500">未取得</dd>}
                  </dl>
                </>
              )}
            </>
          )}
        </Card>
      </div>

      {Object.keys(a.ens_subagents ?? {}).length > 0 && (
        <Card>
          <h2 className="mb-1 font-semibold">Agent の名前空間 <span className="text-xs font-normal text-neutral-500">専門 AI エージェントは Agent 配下の subname。PM Agent はここから候補を選ぶ</span></h2>
          <ul className="mt-2 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(a.ens_subagents).map(([name, recs]) => (
              <li key={name} className="rounded-md border border-neutral-200 p-3">
                <div className="flex items-center gap-2"><Tag>AI</Tag><Mono className="text-neutral-900">{name}</Mono></div>
                <div className="mt-1 text-xs text-neutral-600">{recs["description"] ?? <span className="text-neutral-400">record 未取得</span>}</div>
              </li>
            ))}
          </ul>
        </Card>
      )}
      <EnsRolesTable roles={a.ens_roles} subregistry={a.ens_subregistry} />

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
