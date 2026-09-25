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

  if (!me) return <p className="text-sm text-slate-500">Sign in してください。</p>;
  return (
    <div>
      <PageTitle title="My Agents" action={<Link href="/agents/new"><Button>＋ 新しい PM Agent</Button></Link>} />
      {!data?.length ? <Empty>まだ Agent がありません</Empty> : (
        <div className="space-y-3">
          {data.map((a) => (
            <Card key={a.id} className="flex flex-wrap items-center gap-4">
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2"><Link href={`/agents/${a.id}`} className="font-semibold hover:underline">{a.name}</Link><Badge status={a.status} /></div>
                <div className="mt-1 text-xs text-slate-500">{a.ens_name ? <EnsLink name={a.ens_name} /> : `label: ${a.label}`} {a.ens_tx_hash && <>· <TxLink hash={a.ens_tx_hash} label="ENS tx" /></>}</div>
                {a.ens_error && <div className="mt-1 text-xs text-rose-600">{a.ens_error}</div>}
              </div>
              <div className="text-sm text-slate-500">★{Number(a.rating_avg).toFixed(1)} ({a.rating_count}) · Completed {a.completed_count}</div>
              {(a.status === "draft" || a.status === "publish_failed") && <Button onClick={() => publish.mutate(a.id)} disabled={publish.isPending}>ENS に公開</Button>}
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
