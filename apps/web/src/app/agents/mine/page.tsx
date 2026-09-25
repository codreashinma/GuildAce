"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { api, type Agent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Card, Empty, EnsLink, PageTitle, TxLink } from "@/components/ui";

export default function MyAgents() {
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data } = useQuery({ queryKey: ["agents", "mine", me?.id], queryFn: () => api<Agent[]>("/agents/mine"), enabled: !!me, refetchInterval: 4000 });
  const publish = useMutation({ mutationFn: (id: string) => api(`/agents/${id}/publish`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }) });

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
                <div className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-neutral-500">{a.ens_name ? <EnsLink name={a.ens_name} /> : <span className="font-mono">label: {a.label}</span>}{a.ens_tx_hash && <TxLink hash={a.ens_tx_hash} label="ENS tx" />}</div>
                {a.ens_error && <div className="mt-1 text-xs text-neutral-700">{a.ens_error}</div>}
              </div>
              <div className="whitespace-nowrap text-sm tabular-nums text-neutral-500">★{Number(a.rating_avg).toFixed(1)} ({a.rating_count}) · 実績 {a.completed_count}</div>
              {(a.status === "draft" || a.status === "publish_failed") && <Button onClick={() => publish.mutate(a.id)} disabled={publish.isPending}>ENS に公開</Button>}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
