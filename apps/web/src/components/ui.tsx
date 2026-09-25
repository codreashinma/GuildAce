"use client";

import Link from "next/link";
import { STATUS_LABEL } from "@/lib/api";

export function Button({ className = "", variant = "primary", ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" }) {
  const v = {
    primary: "bg-blue-600 text-white hover:bg-blue-700 disabled:bg-blue-300",
    secondary: "bg-white text-slate-800 border border-slate-300 hover:bg-slate-50 disabled:text-slate-400",
    danger: "bg-rose-600 text-white hover:bg-rose-700 disabled:bg-rose-300",
    ghost: "text-slate-600 hover:bg-slate-100",
  }[variant];
  return <button className={`rounded-lg px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${v} ${className}`} {...p} />;
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-xl border border-slate-200 bg-white p-5 shadow-sm ${className}`}>{children}</div>;
}

const STATUS_COLOR: Record<string, string> = {
  published: "bg-emerald-100 text-emerald-800", publishing: "bg-amber-100 text-amber-800", publish_failed: "bg-rose-100 text-rose-800", draft: "bg-slate-100 text-slate-700",
  planning: "bg-amber-100 text-amber-800", awaiting_approval: "bg-blue-100 text-blue-800", in_progress: "bg-indigo-100 text-indigo-800", delivered: "bg-violet-100 text-violet-800",
  completed: "bg-emerald-100 text-emerald-800", disputed: "bg-rose-100 text-rose-800", resolved: "bg-teal-100 text-teal-800", planning_failed: "bg-rose-100 text-rose-800",
  open: "bg-blue-100 text-blue-800", accepted: "bg-amber-100 text-amber-800", submitted: "bg-violet-100 text-violet-800", done: "bg-emerald-100 text-emerald-800", todo: "bg-slate-100 text-slate-700",
};

export function Badge({ status, children, className = "" }: { status?: string; children?: React.ReactNode; className?: string }) {
  const color = (status && STATUS_COLOR[status]) || "bg-slate-100 text-slate-700";
  return <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color} ${className}`}>{children ?? (status ? STATUS_LABEL[status] ?? status : "")}</span>;
}

export function Stars({ value, count }: { value: number; count?: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-sm">
      <span className="text-amber-500">{"★".repeat(Math.round(value))}{"☆".repeat(5 - Math.round(value))}</span>
      <span className="font-medium">{Number(value).toFixed(1)}</span>
      {count !== undefined && <span className="text-slate-500">({count} Human)</span>}
    </span>
  );
}

export function HumanBadge() {
  return <span className="inline-flex items-center gap-1 rounded-full bg-slate-900 px-2 py-0.5 text-[11px] font-medium text-white">◎ World で人間確認済み</span>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-slate-500">{hint}</span>}
    </label>
  );
}

export const inputCls = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{msg}</div>;
}

export function TxLink({ hash, label = "tx" }: { hash: string | null; label?: string }) {
  if (!hash) return null;
  if (hash.startsWith("0xmock")) return <span className="text-xs text-slate-500">{label}: モック {hash.slice(0, 12)}…</span>;
  return <a className="text-xs text-blue-600 underline" href={`https://sepolia.etherscan.io/tx/${hash}`} target="_blank" rel="noreferrer">{label}: {hash.slice(0, 12)}… ↗</a>;
}

export function EnsLink({ name }: { name: string }) {
  return <a className="font-mono text-sm text-blue-700 hover:underline" href={`https://sepolia.app.ens.domains/${name}`} target="_blank" rel="noreferrer">{name}</a>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-xl border border-dashed border-slate-300 p-10 text-center text-sm text-slate-500">{children}</div>;
}

export function PageTitle({ title, sub, action }: { title: string; sub?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold tracking-tight text-slate-900">{title}</h1>
        {sub && <p className="mt-1 text-sm text-slate-500">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="text-sm text-slate-500 hover:text-slate-800">← {children}</Link>;
}
