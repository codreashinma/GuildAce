"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { usePublishAgent } from "@/components/publish-agent";
import Link from "next/link";
import { useState } from "react";
import { api, short, usdc, type Agent, type AgentEarnings } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Button, Card, Empty, EnsLink, Mono, PageTitle, TxLink } from "@/components/ui";

/** D3 / API-18: Agent の収益。案件ごとの PM 管理費（PM 工程）を Escrow の投影から集計して表示する。金額の正本は Escrow の tx */
function Earnings({ agentId }: { agentId: string }) {
  const { data, error } = useQuery({ queryKey: ["agent-earnings", agentId], queryFn: () => api<AgentEarnings>(`/agents/${agentId}/earnings`), refetchInterval: 8000 });
  if (error) return <p className="text-xs text-neutral-700">{(error as Error).message}</p>;
  if (!data) return <p className="text-xs text-neutral-500">読み込み中…</p>;
  return (
    <div className="w-full border-t border-neutral-200 pt-3">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-sm">
        <div className="whitespace-nowrap">受取済 <Amount value={usdc(data.paid_total)} /></div>
        <div className="whitespace-nowrap text-neutral-600">預託中（未払い） <span className="tabular-nums">{usdc(data.pending_total)}</span> USDC</div>
        {Number(data.resolved_total) > 0 && <div className="whitespace-nowrap text-neutral-600">裁定で受取 <span className="tabular-nums">{usdc(data.resolved_total)}</span> USDC</div>}
        <div className="whitespace-nowrap text-xs text-neutral-500">案件 {data.cases} 件 · 利用料 {(data.fee_bps / 100).toFixed(1)}% · 受取先 <span title={data.payout_address}><Mono>{short(data.payout_address)}</Mono></span></div>
      </div>
      {data.rows.length === 0 ? <p className="mt-2 text-xs text-neutral-500">まだ PM 管理費の預託はありません。案件が開始（openCase）されると、PM 工程がここに並びます。</p> : (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">日時</th><th className="pr-3">案件</th><th className="pr-3 text-right">予算</th><th className="pr-3 text-right">PM 管理費</th><th className="pr-3 text-right">受取額</th><th className="pr-3">状態</th><th>tx</th></tr></thead>
            <tbody>
              {data.rows.map((r) => (
                <tr key={r.task_id} className="border-t border-neutral-100 [&>td]:py-1.5 [&>td]:pr-3">
                  <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{r.at ? new Date(r.at).toLocaleString("ja-JP") : "—"}</td>
                  <td className="min-w-40"><Link href={`/cases/${r.case_id}`} className="underline-offset-2 hover:underline">{r.case_title}</Link> <Badge status={r.case_status} /></td>
                  <td className="whitespace-nowrap text-right tabular-nums text-neutral-500">{usdc(r.budget)}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{usdc(r.amount)}</td>
                  <td className="whitespace-nowrap text-right tabular-nums">{usdc(r.received)}{r.chain_status === "resolved" && Number(r.received) === 0 && <span className="ml-1 text-xs text-neutral-500">（返金）</span>}</td>
                  <td><Badge status={`chain:${r.chain_status}`} /></td>
                  <td><TxLink hash={r.tx_hash} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function MyAgents() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["agents", "mine", me?.id], queryFn: () => api<Agent[]>("/agents/mine"), enabled: !!me, refetchInterval: 4000 });
  const { publish: doPublish, step } = usePublishAgent();
  const publish = useMutation({ mutationFn: (id: string) => doPublish(id), onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }) });
  const [open, setOpen] = useState<Record<string, boolean>>({});

  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  return (
    <div>
      <PageTitle title="My Agents" action={<Link href="/agents/new"><Button>＋ 新しい PM Agent</Button></Link>} />
      {!data?.length ? <Empty>まだ Agent がありません</Empty> : (
        <div className="space-y-3">
          {data.map((a) => (
            <Card key={a.id} className="flex flex-wrap items-center gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 items-center gap-2"><Link href={`/agents/${a.id}`} className="truncate font-semibold underline-offset-2 hover:underline">{a.name}</Link><Badge status={a.status} /></div>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-neutral-500">{a.ens_name ? <EnsLink name={a.ens_name} /> : <span className="font-mono">{a.label}.{a.parent_ens_name ?? "guildace.eth"}</span>}{a.owner_mode === "creator" && <Badge>Creator 所有</Badge>}{a.ens_subregistry && <Badge status="published">名前空間</Badge>}{a.ens_tx_hash && <TxLink hash={a.ens_tx_hash} label="ENS tx" />}</div>
                {a.ens_error && <div className="mt-1 text-xs text-neutral-700">{a.ens_error}</div>}
              </div>
              <div className="whitespace-nowrap text-sm tabular-nums text-neutral-500">★{Number(a.rating_avg).toFixed(1)} ({a.rating_count}) · 実績 {a.completed_count}</div>
              <Button variant="secondary" onClick={() => setOpen((o) => ({ ...o, [a.id]: !o[a.id] }))}>{open[a.id] ? "収益を閉じる" : "収益"}</Button>
              <Link href={`/agents/${a.id}/edit`}><Button variant="secondary">編集</Button></Link>
              {(a.status === "draft" || a.status === "publish_failed") && <Button onClick={() => publish.mutate(a.id)} disabled={publish.isPending}>{step ?? "ENS に公開"}</Button>}
              {((a.status === "published" && a.ens_error) || a.status === "publishing") && a.owner_mode === "creator" && <Button onClick={() => publish.mutate(a.id)} disabled={publish.isPending}>{step ?? "残りの tx に署名"}</Button>}
              {open[a.id] && <Earnings agentId={a.id} />}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
