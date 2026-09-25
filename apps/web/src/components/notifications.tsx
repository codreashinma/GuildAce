"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { noticesFromCases } from "@/lib/mock";

const ICON: Record<string, string> = { approve: "承認", deliver: "提出", pay: "支払", dispute: "紛争", info: "進行" };

/** FR-032 関係者への通知（UI モック: 自分の案件の状態から組み立てる） */
export function NotificationBell() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["cases", me?.id], queryFn: () => api<Case[]>("/cases"), enabled: !!me, refetchInterval: 8000 });
  if (!me) return null;
  const notices = noticesFromCases(data ?? []);
  const urgent = notices.filter((n) => n.kind === "approve" || n.kind === "deliver" || n.kind === "dispute").length;
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} className="relative inline-flex h-9 items-center whitespace-nowrap rounded-md border border-neutral-300 px-2.5 text-xs text-neutral-700 hover:border-neutral-900 hover:text-neutral-900" title="通知">
        通知
        {urgent > 0 && <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm bg-neutral-900 px-1 text-[10px] tabular-nums text-white">{urgent}</span>}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-md border border-neutral-900 bg-white p-2 shadow-[4px_4px_0_0_#171717]">
          <div className="px-2 py-1 text-xs font-semibold text-neutral-500">通知</div>
          {notices.length === 0 ? <p className="px-2 py-3 text-sm text-neutral-500">通知はありません</p> : (
            <ul className="max-h-80 overflow-auto">
              {notices.map((n) => (
                <li key={n.id}><Link href={n.href} onClick={() => setOpen(false)} className="flex gap-2 rounded-md px-2 py-2 text-sm hover:bg-neutral-100"><span className="mt-0.5 inline-flex h-5 shrink-0 items-center rounded-sm border border-neutral-900 px-1 text-[10px] font-semibold">{ICON[n.kind]}</span><span className="min-w-0"><div className="font-medium">{n.title}</div><div className="truncate text-xs text-neutral-500">{n.body}</div></span></Link></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
