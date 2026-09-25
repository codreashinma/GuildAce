"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, usdc, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Card, Empty, PageTitle } from "@/components/ui";

export default function Cases() {
  const { me } = useAuth();
  const { data } = useQuery({ queryKey: ["cases", me?.id], queryFn: () => api<Case[]>("/cases"), enabled: !!me, refetchInterval: 5000 });
  if (!me) return <p className="text-sm text-slate-500">Sign in してください。</p>;
  return (
    <div>
      <PageTitle title="案件" sub="あなたが発注した案件" action={<Link href="/cases/new"><Button>＋ 案件を作成</Button></Link>} />
      {!data?.length ? <Empty>案件がまだありません</Empty> : (
        <div className="space-y-3">
          {data.map((c) => (
            <Link key={c.id} href={`/cases/${c.id}`} className="block">
              <Card className="flex flex-wrap items-center gap-4 hover:bg-slate-50">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2"><span className="font-semibold">{c.title}</span><Badge status={c.status} /></div>
                  <div className="mt-1 text-xs text-slate-500">PM: {c.agent.name} · {c.agent.ens_name}</div>
                </div>
                <div className="text-sm"><b>{usdc(c.budget)}</b> USDC</div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
