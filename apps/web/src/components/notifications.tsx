"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Notice } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const ICON: Record<string, string> = { approve: "Approval", assigned: "Assigned", deliver: "Submitted", pay: "Payment", dispute: "Dispute", info: "Update" };

/** FR-032 関係者への通知（API が承認待ち・指名・提出・支払い・紛争を横断して返す） */
export function NotificationBell() {
  const { me } = useAuth();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["notifications", me?.id], queryFn: () => api<Notice[]>("/cases/notifications"), enabled: !!me, refetchInterval: 8000 });
  if (!me) return null;
  const notices = data ?? [];
  const urgent = notices.filter((n) => n.urgent).length;
  return (
    <div className="relative">
      <button onClick={() => setOpen((v) => !v)} className="relative inline-flex h-9 items-center whitespace-nowrap rounded-md border border-neutral-600 px-2.5 text-xs text-white hover:border-white" title="Notifications" aria-label="Notifications">
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {urgent > 0 && <span className="ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-sm bg-white px-1 text-[10px] tabular-nums text-neutral-900">{urgent}</span>}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-md border border-neutral-900 bg-white p-2 shadow-[4px_4px_0_0_#171717]">
          <div className="px-2 py-1 text-xs font-semibold text-neutral-500">Notifications</div>
          {notices.length === 0 ? <p className="px-2 py-3 text-sm text-neutral-500">No notifications</p> : (
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
