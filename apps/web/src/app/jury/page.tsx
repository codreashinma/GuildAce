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
      <PageTitle title="Human Jury" sub="When the Client and the Agent cannot agree, a majority vote of 3 World-verified third parties decides where the funds go" action={
        <div className="flex rounded-md border border-neutral-900 text-sm">{(["open", "closed"] as const).map((s) => <button key={s} onClick={() => setStatus(s)} className={`whitespace-nowrap px-3 py-1 ${status === s ? "bg-neutral-900 text-white" : "text-neutral-700"}`}>{s === "open" ? "Under review" : "Closed"}</button>)}</div>
      } />
      {!data?.length ? <Empty>{status === "open" ? "No disputes under review" : "No closed disputes"}</Empty> : (
        <div className="space-y-3">
          {data.map((d) => (
            <Link key={d.id} href={`/jury/${d.id}`}>
              <Card className="flex flex-wrap items-center gap-4 transition hover:border-neutral-900">
                <div className="min-w-0 flex-1">
                  <div className="flex min-w-0 items-center gap-2"><span className="truncate font-semibold">{d.case.title}</span><Badge status={d.status === "open" ? "disputed" : "resolved"}>{d.status === "open" ? "Under review" : `Closed: ${d.outcome === "release" ? "Payment" : "Refund"}`}</Badge></div>
                  <p className="mt-1 line-clamp-1 text-sm text-neutral-600">{d.reason}</p>
                </div>
                <div className="whitespace-nowrap text-sm"><Amount value={usdc(d.case.budget)} /> held</div>
                <div className="whitespace-nowrap text-sm tabular-nums text-neutral-500">Votes {d.votes.length}/{d.required_votes}</div>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
