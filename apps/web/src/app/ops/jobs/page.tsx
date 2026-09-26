"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, usdc, type ChainJob, type ChainJobStatus, type OpsJobs } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Card, Empty, ErrorBox, Mono, PageTitle, TxLink, selectCls } from "@/components/ui";

const STATUS: Record<ChainJobStatus, string> = { queued: "Queued", running: "Sending", retry: "Waiting to retry", done: "Confirmed", failed: "Failed" };
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

  if (loading) return <p className="text-sm text-neutral-500">Loading…</p>;
  if (!me) return <p className="text-sm text-neutral-500">Please sign in.</p>;
  if (!me.is_ops) return <p className="text-sm text-neutral-700">This page is only available to operators (wallets registered in the API&apos;s <Mono>OPS_ADDRESSES</Mono>).</p>;

  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;
  return (
    <div className="space-y-6">
      <PageTitle title="Chain Jobs" sub="All writes to Escrow and ENS go through these jobs (chain_jobs). Idempotency keys prevent double sends, and failures are retried automatically up to 5 times. Jobs that fail 5 times can be requeued here." />

      <Card>
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 text-sm">
          <div className="whitespace-nowrap">Worker <Badge status={data?.worker_alive ? "published" : "publish_failed"}>{data ? (data.worker_alive ? "Running" : "Stopped") : "—"}</Badge></div>
          {STATUS_ORDER.map((s) => (
            <button key={s} type="button" onClick={() => setStatus(status === s ? "" : s)} className={`whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs tabular-nums ${status === s ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-700 hover:border-neutral-900"}`}>
              {STATUS[s]} {data?.counts[s] ?? 0}
            </button>
          ))}
          <div className="whitespace-nowrap text-xs text-neutral-500">Total {total}</div>
          <select className={`${selectCls} ml-auto`} value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All types</option>
            {data?.kinds.map((k) => <option key={k} value={k}>{k}</option>)}
          </select>
        </div>
      </Card>

      {error && <ErrorBox error={error} />}
      {retry.error && <ErrorBox error={retry.error} />}

      <Card>
        {!data ? <p className="text-sm text-neutral-500">Loading…</p> : data.jobs.length === 0 ? <Empty>No matching jobs</Empty> : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500">
                <tr><th className="py-1 pr-3">Status</th><th className="pr-3">Action</th><th className="pr-3">Type</th><th className="pr-3">Target</th><th className="pr-3 text-right">Amount</th><th className="pr-3">Attempts</th><th className="pr-3">tx</th><th className="pr-3">Updated</th><th>Error</th></tr>
              </thead>
              <tbody>
                {data.jobs.map((j) => (
                  <tr key={j.id} className="border-t border-neutral-100 align-top [&>td]:py-2 [&>td]:pr-3">
                    <td><Badge status={j.status === "done" ? "completed" : j.status === "failed" ? "publish_failed" : j.status === "running" ? "in_progress" : undefined}>{STATUS[j.status]}</Badge></td>
                    <td className="whitespace-nowrap">{j.retryable ? <Button variant="secondary" onClick={() => retry.mutate(j.id)} disabled={retry.isPending}>Requeue</Button> : <span className="text-xs text-neutral-400">{j.status === "retry" ? "Auto retry" : "—"}</span>}</td>
                    <td className="min-w-40 max-w-64"><div className="whitespace-nowrap">{j.label}</div><div className="truncate text-[11px] text-neutral-400" title={j.idempotency_key}><Mono>{j.idempotency_key}</Mono></div></td>
                    <td className="min-w-40 text-xs">
                      {j.case_title && <div>{j.href ? <Link href={j.href} className="underline-offset-2 hover:underline">{j.case_title}</Link> : j.case_title}</div>}
                      {j.task_title && <div className="text-neutral-500">{j.task_title}</div>}
                      {j.agent_name && <div>{j.href ? <Link href={j.href} className="underline-offset-2 hover:underline">{j.agent_name}</Link> : j.agent_name}</div>}
                      {!j.case_title && !j.agent_name && <span className="text-neutral-400">—</span>}
                    </td>
                    <td className="whitespace-nowrap text-right tabular-nums">{j.amount ? `${usdc(j.amount)} USDC` : ""}</td>
                    <td className="whitespace-nowrap tabular-nums text-xs">{j.attempts} / {j.max_attempts}{j.next_attempt_at && j.status === "retry" && <div className="text-neutral-500">Next {new Date(j.next_attempt_at).toLocaleTimeString("en-US")}</div>}</td>
                    <td><TxLink hash={j.tx_hash} /></td>
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{new Date(j.updated_at).toLocaleString("en-US")}</td>
                    <td className="min-w-64 max-w-md"><div className="line-clamp-3 break-all text-xs text-neutral-700" title={j.error ?? ""}>{j.error ?? ""}</div></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-neutral-500">Only failed jobs (all 5 automatic retries used up) can be requeued; jobs waiting to retry are resent by the worker automatically. Requeuing resets the attempt count to 0 and sends a new tx, so for Escrow jobs the on-chain step status is checked first and the requeue is refused if it is already applied (the tx was sent and only the receipt check failed). In that case, use &quot;Resync&quot; on the case detail page to rebuild the projection. Requeuing an ENS publish job sets the agent back to &quot;Publishing to ENS&quot;.</p>
      </Card>
    </div>
  );
}
