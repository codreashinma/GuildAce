"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, usdc, type Dispute } from "@/lib/api";
import { Amount, Badge, Card, Empty, PageTitle } from "@/components/ui";

export default function Jury() {
  const [status, setStatus] = useState<"open" | "closed">("open");
  const { data } = useQuery({ queryKey: ["disputes", status], queryFn: () => api<Dispute[]>(`/disputes?status=${status}`), refetchInterval: 5000 });
  return (
    <div>
      <PageTitle title="Human Jury" sub="発注者と Agent が合意できないとき、World で証明された第三者 3 名の多数決で資金の行き先を決めます" action={
        <div className="flex rounded-md border border-neutral-900 text-sm">{(["open", "closed"] as const).map((s) => <button key={s} onClick={() => setStatus(s)} className={`whitespace-nowrap px-3 py-1 ${status === s ? "bg-neutral-900 text-white" : "text-neutral-700"}`}>{s === "open" ? "審理中" : "終了"}</button>)}</div>
      } />
      {!data?.length ? <Empty>{status === "open" ? "審理中の紛争はありません" : "終了した紛争はありません"}</Empty> : (
        <div className="space-y-3">
          {data.map((d) => (
            <Link key={d.id} href={`/jury/${d.id}`}>
              <Card className="flex flex-wrap items-center gap-4 transition hover:border-neutral-900">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2"><span className="truncate font-semibold">{d.case.title}</span><Badge status={d.status === "open" ? "disputed" : "resolved"}>{d.status === "open" ? "審理中" : `終了: ${d.outcome === "release" ? "支払い" : "返金"}`}</Badge></div>
                  <p className="mt-1 line-clamp-1 text-sm text-neutral-600">{d.reason}</p>
                </div>
                <div className="whitespace-nowrap text-sm"><Amount value={usdc(d.case.budget)} /> 保留中</div>
                <div className="whitespace-nowrap text-sm tabular-nums text-neutral-500">投票 {d.votes.length}/{d.required_votes}</div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
