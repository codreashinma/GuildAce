"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { noticesFromCases } from "@/lib/mock";

const ICON = { approve: "✅", deliver: "📦", pay: "💸", dispute: "⚖️", info: "🛠" };

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
      <button onClick={() => setOpen((v) => !v)} className="relative grid h-9 w-9 place-items-center rounded-lg hover:bg-slate-100" title="通知">
        🔔
        {urgent > 0 && <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-rose-600 px-1 text-[10px] text-white">{urgent}</span>}
      </button>
      {open && (
        <div className="absolute right-0 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-2 shadow-lg">
          <div className="px-2 py-1 text-xs font-semibold text-slate-500">通知</div>
          {notices.length === 0 ? <p className="px-2 py-3 text-sm text-slate-500">通知はありません</p> : (
            <ul className="max-h-80 overflow-auto">
              {notices.map((n) => (
                <li key={n.id}><Link href={n.href} onClick={() => setOpen(false)} className="flex gap-2 rounded-lg px-2 py-2 text-sm hover:bg-slate-50"><span>{ICON[n.kind]}</span><span><div className="font-medium">{n.title}</div><div className="text-xs text-slate-500">{n.body}</div></span></Link></li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
