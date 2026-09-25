"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, usdc, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Button, Card, Empty, Mono, PageTitle } from "@/components/ui";

export default function Cases() {
  const { me } = useAuth();
  const { data } = useQuery({ queryKey: ["cases", me?.id], queryFn: () => api<Case[]>("/cases"), enabled: !!me, refetchInterval: 5000 });
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  return (
    <div>
      <PageTitle title="案件" sub="あなたが発注した案件と、承認者として関わる案件" action={<Link href="/cases/new"><Button>＋ 案件を作成</Button></Link>} />
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
