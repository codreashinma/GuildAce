"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { api, usdc, type Case, type PendingApproval } from "@/lib/api";
import { ApproveButton } from "@/components/approve-button";
import { KindTag } from "@/components/ui";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Button, Card, Empty, Mono, PageTitle } from "@/components/ui";

export default function Cases() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["cases", me?.id], queryFn: () => api<Case[]>("/cases"), enabled: !!me, refetchInterval: 5000 });
  const { data: pending } = useQuery({ queryKey: ["pending-approvals", me?.id], queryFn: () => api<PendingApproval[]>("/cases/pending-approvals"), enabled: !!me, refetchInterval: 5000 });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["pending-approvals"] }); qc.invalidateQueries({ queryKey: ["cases"] }); qc.invalidateQueries({ queryKey: ["notifications"] }); };
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  return (
    <div>
      <PageTitle title="案件" sub="あなたが発注した案件と、承認者として関わる案件" action={<Link href="/cases/new"><Button>＋ 案件を作成</Button></Link>} />
      {pending && pending.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-1 font-semibold">あなたの承認待ち <span className="text-sm font-normal tabular-nums text-neutral-500">{pending.length} 工程</span></h2>
          <p className="mb-3 text-xs text-neutral-500">World で人間確認をして (成果物ハッシュ, 支払先) に署名します。必要数がそろった工程から Escrow が自動で支払います。</p>
          <div className="space-y-2">
            {pending.map((p) => (
              <Card key={p.task_id} className="flex flex-wrap items-center gap-4">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2"><KindTag kind={p.task_type} /><span className="truncate font-medium">{p.task_title}</span></div>
                  <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-neutral-500"><Link href={`/cases/${p.case_id}`} className="truncate underline underline-offset-2">{p.case_title}</Link><span className="whitespace-nowrap">支払先 <Mono>{p.payee ? `${p.payee.slice(0, 6)}…${p.payee.slice(-4)}` : "-"}</Mono></span><span className="whitespace-nowrap">ハッシュ <Mono>{p.deliverable_hash?.slice(0, 12)}…</Mono></span></div>
                </div>
                <Amount value={usdc(p.amount)} className="text-sm font-semibold" />
                <ApproveButton caseId={p.case_id} taskId={p.task_id} deliverableHash={p.deliverable_hash} approvalCount={p.approval_count} threshold={p.threshold} alreadyApproved={false} onDone={refresh} />
              </Card>
            ))}
          </div>
        </section>
      )}
      {!data?.length ? <Empty>案件がまだありません</Empty> : (
        <div className="space-y-3">
          {data.map((c) => (
            <Link key={c.id} href={`/cases/${c.id}`} className="block">
              <Card className="flex flex-wrap items-center gap-4 transition hover:border-neutral-900">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2"><span className="truncate font-semibold">{c.title}</span><Badge status={c.status} /></div>
                  <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-neutral-500"><span className="whitespace-nowrap">PM: {c.agent.name}</span><Mono>{c.agent.ens_name}</Mono></div>
                </div>
                <Amount value={usdc(c.budget)} className="text-sm font-semibold" />
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
