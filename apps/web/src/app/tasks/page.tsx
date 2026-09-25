"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, usdc, type HumanTask } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Card, Empty, KindTag, PageTitle } from "@/components/ui";

function List({ items }: { items: HumanTask[] }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {items.map((t) => (
        <Link key={t.id} href={`/tasks/${t.id}`}>
          <Card className="h-full transition hover:border-neutral-900">
            <div className="flex items-center justify-between gap-2"><span className="flex min-w-0 items-center gap-2 font-semibold"><KindTag kind="human" /><span className="truncate">{t.title}</span></span><Badge status={t.status} /></div>
            <p className="mt-1 line-clamp-2 text-sm text-neutral-600">{t.description}</p>
            {t.assignee && <p className="mt-1 flex items-center gap-1 text-xs text-neutral-900"><span className="whitespace-nowrap">指名:</span><span className="truncate font-mono">{t.assignee.ens_name}</span></p>}
            <div className="mt-3 text-sm">報酬 <Amount value={usdc(t.reward)} className="font-semibold" /></div>
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
  const { data: assigned } = useQuery({ queryKey: ["human-tasks", "assigned", me?.id], queryFn: () => api<HumanTask[]>("/human-tasks/assigned"), enabled: !!me, refetchInterval: 5000 });
  return (
    <div className="space-y-8">
      {assigned && assigned.length > 0 && (
        <div>
          <h2 className="mb-1 font-semibold">あなたへの指名</h2>
          <p className="mb-3 text-xs text-neutral-500">PM Agent が ENS 上のあなたのプロフィール（<span className="font-mono">{assigned[0].assignee?.ens_name}</span>）を見て指名しました。World で人間確認をして受諾するか、辞退してください</p>
          <List items={assigned} />
        </div>
      )}
      <div>
        <PageTitle title="Human Task Marketplace" sub="AI にはできない仕事。PM Agent が ENS 上の会社の人員から指名し、候補がいなければここで公開募集します。受注には World の人間確認が必要です" />
        {!data?.length ? <Empty>募集中の Human Task はありません。案件が進むと PM Agent がここに発注します</Empty> : <List items={data} />}
      </div>
      {mine && mine.length > 0 && <div><h2 className="mb-3 font-semibold">自分が受注したタスク</h2><List items={mine} /></div>}
    </div>
  );
}
