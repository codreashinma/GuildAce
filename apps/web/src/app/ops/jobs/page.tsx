"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, usdc, type ChainJob, type ChainJobStatus, type OpsJobs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Card, Empty, ErrorBox, Mono, PageTitle, TxLink, selectCls } from "@/components/ui";

const STATUS: Record<ChainJobStatus, string> = { queued: "送信待ち", running: "送信中", retry: "再送待ち", done: "確定", failed: "失敗" };
const STATUS_ORDER: ChainJobStatus[] = ["failed", "retry", "running", "queued", "done"];

/** G1: チェーン連携ジョブ（chain_jobs）の状態・失敗の再送・tx リンク（GET /ops/jobs, POST /ops/jobs/{id}/retry）。
 *  運用者（OPS_ADDRESSES）だけが使える。Escrow と ENS への書き込みはすべてこのジョブ経由（ADR-006: 冪等キー・再送 5 回・単一スレッド） */
export default function OpsJobsPage() {
  const { me, loading } = useAuth();
  const qc = useQueryClient();
  const [status, setStatus] = useState<string>("");
  const [kind, setKind] = useState<string>("");
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (kind) params.set("kind", kind);
  const qs = params.toString();
  const { data, error } = useQuery({ queryKey: ["ops-jobs", qs, me?.id], queryFn: () => api<OpsJobs>(`/ops/jobs${qs ? `?${qs}` : ""}`), enabled: !!me?.is_ops, refetchInterval: 5000 });
  const retry = useMutation({ mutationFn: (id: string) => api<ChainJob>(`/ops/jobs/${id}/retry`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["ops-jobs"] }) });

  if (loading) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  if (!me.is_ops) return <p className="text-sm text-neutral-700">この画面は運用者（API の <Mono>OPS_ADDRESSES</Mono> に登録したウォレット）だけが使えます。</p>;

  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;
  return (
    <div className="space-y-6">
      <PageTitle title="チェーン連携ジョブ" sub="Escrow と ENS への書き込みはすべてこのジョブ（chain_jobs）を経由します。冪等キーで二重送信を防ぎ、失敗は最大 5 回まで自動で再送します。5 回失敗したジョブはここから再投入できます。" />

      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <div className="whitespace-nowrap">ワーカー <Badge status={data?.worker_alive ? "published" : "publish_failed"}>{data ? (data.worker_alive ? "稼働中" : "停止") : "—"}</Badge></div>
          {STATUS_ORDER.map((s) => (
            <button key={s} type="button" onClick={() => setStatus(status === s ? "" : s)} className={`whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs tabular-nums ${status === s ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-700 hover:border-neutral-900"}`}>
              {STATUS[s]} {data?.counts[s] ?? 0}
            </button>
          ))}
          <div className="whitespace-nowrap text-xs text-neutral-500">合計 {total}</div>
          <select className={`${selectCls} ml-auto`} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">すべての種類</option>
            {data?.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
      </Card>

      {error && <ErrorBox error={error} />}
      {retry.error && <ErrorBox error={retry.error} />}

      <Card>
        {!data ? <p className="text-sm text-neutral-500">読み込み中…</p> : data.jobs.length === 0 ? <Empty>該当するジョブはありません</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500">
                <tr><th className="py-1 pr-3">状態</th><th className="pr-3">操作</th><th className="pr-3">種類</th><th className="pr-3">対象</th><th className="pr-3 text-right">金額</th><th className="pr-3">試行</th><th className="pr-3">tx</th><th className="pr-3">更新</th><th>エラー</th></tr>
              </thead>
              <tbody>
                {data.jobs.map((j) => (
                  <tr key={j.id} className="border-t border-neutral-100 align-top [&>td]:py-2 [&>td]:pr-3">
                    <td><Badge status={j.status === "done" ? "completed" : j.status === "failed" ? "publish_failed" : j.status === "running" ? "in_progress" : undefined}>{STATUS[j.status]}</Badge></td>
                    <td className="whitespace-nowrap">{j.retryable ? <Button variant="secondary" onClick={() => retry.mutate(j.id)} disabled={retry.isPending}>再投入</Button> : <span className="text-xs text-neutral-400">{j.status === "retry" ? "自動再送" : "—"}</span>}</td>
                    <td className="min-w-40 max-w-64"><div className="whitespace-nowrap">{j.label}</div><div className="truncate text-[11px] text-neutral-400" title={j.idempotency_key}><Mono>{j.idempotency_key}</Mono></div></td>
                    <td className="min-w-40 text-xs">
                      {j.case_title && <div>{j.href ? <Link href={j.href} className="underline-offset-2 hover:underline">{j.case_title}</Link> : j.case_title}</div>}
                      {j.task_title && <div className="text-neutral-500">{j.task_title}</div>}
                      {j.agent_name && <div>{j.href ? <Link href={j.href} className="underline-offset-2 hover:underline">{j.agent_name}</Link> : j.agent_name}</div>}
                      {!j.case_title && !j.agent_name && <span className="text-neutral-400">—</span>}
                    </td>
                    <td className="whitespace-nowrap text-right tabular-nums">{j.amount ? `${usdc(j.amount)} USDC` : ""}</td>
                    <td className="whitespace-nowrap tabular-nums text-xs">{j.attempts} / {j.max_attempts}{j.next_attempt_at && j.status === "retry" && <div className="text-neutral-500">次 {new Date(j.next_attempt_at).toLocaleTimeString("ja-JP")}</div>}</td>
                    <td><TxLink hash={j.tx_hash} /></td>
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{new Date(j.updated_at).toLocaleString("ja-JP")}</td>
                    <td className="min-w-64 max-w-md"><div className="line-clamp-3 break-all text-xs text-neutral-700" title={j.error ?? ""}>{j.error ?? ""}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-neutral-500">再投入できるのは失敗（自動再送 5 回を使い切った）ジョブだけで、再送待ちはワーカーが自動で再送します。再投入は試行回数を 0 に戻して新しい tx を送るため、Escrow 系のジョブはオンチェーンの工程状態を確認し、既に反映済み（tx は送信済みで受信確認だけが失敗）なら断ります。その場合は案件詳細の「再同期」で投影を取り直してください。ENS 公開のジョブは Agent を「公開中」に戻します。</p>
      </Card>
    </div>
  );
}
