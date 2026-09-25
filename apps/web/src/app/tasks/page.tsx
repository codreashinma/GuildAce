"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, usdc, type HumanTask } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Card, Empty, PageTitle } from "@/components/ui";

function List({ items }: { items: HumanTask[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map((t) => (
        <Link key={t.id} href={`/tasks/${t.id}`}>
          <Card className="h-full hover:bg-slate-50">
            <div className="flex items-center justify-between gap-2"><span className="font-semibold">🧑 {t.title}</span><Badge status={t.status} /></div>
            <p className="mt-1 line-clamp-2 text-sm text-slate-600">{t.description}</p>
            <div className="mt-3 text-sm">報酬 <b>{usdc(t.reward)} USDC</b></div>
          </Card>
        </Link>
      ))}
    </div>
  );
}

export default function Tasks() {
  const { me } = useAuth();
  const { data } = useQuery({ queryKey: ["human-tasks"], queryFn: () => api<HumanTask[]>("/human-tasks"), refetchInterval: 5000 });
  const { data: mine } = useQuery({ queryKey: ["human-tasks", "mine", me?.id], queryFn: () => api<HumanTask[]>("/human-tasks/mine"), enabled: !!me });
  return (
    <div className="space-y-8">
      <div>
        <PageTitle title="Human Task Marketplace" sub="AI にはできない仕事。World で証明された人間だけが受注できます" />
        {!data?.length ? <Empty>募集中の Human Task はありません。案件が進むと PM Agent がここに発注します</Empty> : <List items={data} />}
      </div>
      {mine && mine.length > 0 && <div><h2 className="mb-3 font-semibold">自分が受注したタスク</h2><List items={mine} /></div>}
    </div>
  );
}
