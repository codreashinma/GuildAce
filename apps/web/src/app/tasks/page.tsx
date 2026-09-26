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
            {t.assignee && <p className="mt-1 flex items-center gap-1 text-xs text-neutral-900"><span className="whitespace-nowrap">Assigned:</span><span className="truncate font-mono">{t.assignee.ens_name}</span></p>}
            <div className="mt-3 text-sm">Reward <Amount value={usdc(t.reward)} className="font-semibold" /></div>
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
          <h2 className="mb-1 font-semibold">Assigned to you</h2>
          <p className="mb-3 text-xs text-neutral-500">The PM Agent assigned you based on your profile on ENS (<span className="font-mono">{assigned[0].assignee?.ens_name}</span>). Verify with World to accept, or decline.</p>
          <List items={assigned} />
        </div>
      )}
      <div>
        <PageTitle title="Human Task Marketplace" sub="Work AI can't do. The PM Agent assigns it to company members on ENS, and posts it here publicly if no candidate is found. Accepting requires World human verification." />
        {!data?.length ? <Empty>No open Human Tasks. The PM Agent will post tasks here as cases progress.</Empty> : <List items={data} />}
      </div>
      {mine && mine.length > 0 && <div><h2 className="mb-3 font-semibold">Tasks I accepted</h2><List items={mine} /></div>}
    </div>
  );
}
