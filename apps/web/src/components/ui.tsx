"use client";

import Link from "next/link";
import { STATUS_LABEL } from "@/lib/api";

/* ---------- ボタン（モノトーン。ラベルは折り返さない） ---------- */
export function Button({ className = "", variant = "primary", ...p }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" | "ghost" | "inverse" | "outline-inverse" }) {
  const v = {
    inverse: "bg-white text-neutral-900 hover:bg-neutral-200",
    "outline-inverse": "border border-white bg-transparent text-white hover:bg-neutral-800",
    primary: "bg-neutral-900 text-white hover:bg-neutral-700 disabled:bg-neutral-300",
    secondary: "bg-white text-neutral-900 border border-neutral-900 hover:bg-neutral-100 disabled:border-neutral-300 disabled:text-neutral-400",
    danger: "bg-white text-neutral-900 border border-neutral-400 border-dashed hover:border-neutral-900 disabled:text-neutral-400",
    ghost: "text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900",
  }[variant];
  return <button className={`inline-flex items-center justify-center gap-1 whitespace-nowrap rounded-md px-4 py-2 text-sm font-medium transition disabled:cursor-not-allowed ${v} ${className}`} {...p} />;
}

export function Card({ className = "", children }: { className?: string; children: React.ReactNode }) {
  return <div className={`rounded-lg border border-neutral-200 bg-white p-5 ${className}`}>{children}</div>;
}

/* ---------- 状態バッジ。完了系は塗り、進行中は枠、注意系は太枠 ---------- */
const FILLED = new Set(["published", "completed", "done", "chain:paid", "chain:resolved", "resolved"]);
const STRONG = new Set(["publish_failed", "planning_failed", "disputed", "chain:disputed"]);
const ACTIVE = new Set(["publishing", "planning", "in_progress", "accepted", "assigned", "chain:submitted", "delivered", "awaiting_approval", "submitted"]);

export function Badge({ status, children, className = "" }: { status?: string; children?: React.ReactNode; className?: string }) {
  let style = "border border-neutral-300 text-neutral-700";
  if (status && FILLED.has(status)) style = "border border-neutral-900 bg-neutral-900 text-white";
  else if (status && STRONG.has(status)) style = "border-2 border-neutral-900 text-neutral-900 font-semibold";
  else if (status && ACTIVE.has(status)) style = "border border-neutral-900 text-neutral-900";
  return (
    <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-sm px-2 py-0.5 text-[11px] leading-5 tracking-wide ${style} ${className}`}>
      {children ?? (status ? STATUS_LABEL[status] ?? status : "")}
    </span>
  );
}

export function Stars({ value, count }: { value: number; count?: number }) {
  const v = Number(value);
  return (
    <span className="inline-flex items-center gap-1 whitespace-nowrap text-sm tabular-nums">
      <span className="tracking-tight text-neutral-900" aria-hidden>{"★".repeat(Math.round(v))}<span className="text-neutral-300">{"★".repeat(5 - Math.round(v))}</span></span>
      <span className="font-medium">{v.toFixed(1)}</span>
      {count !== undefined && <span className="text-neutral-500">({count} Human)</span>}
    </span>
  );
}

export function HumanBadge() {
  return <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border border-neutral-900 px-1.5 py-0.5 text-[10px] font-medium leading-4 text-neutral-900">◎ World 人間確認済</span>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium tracking-wide text-neutral-700">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-neutral-500">{hint}</span>}
    </label>
  );
}

export const selectCls = "rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";
export const inputCls = "w-full rounded-md border border-neutral-300 bg-white px-3 py-2 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-900 focus:outline-none focus:ring-1 focus:ring-neutral-900";

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-md border-l-2 border-neutral-900 bg-neutral-100 px-3 py-2 text-sm text-neutral-900">{msg}</div>;
}

/* ---------- ハッシュ・アドレス・ENS 名（等幅。途中改行させず、はみ出す場合だけ切る） ---------- */
export function Mono({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`inline-block max-w-full truncate align-bottom font-mono text-[12px] text-neutral-700 ${className}`}>{children}</span>;
}

export function TxLink({ hash, label = "tx" }: { hash: string | null; label?: string }) {
  if (!hash) return null;
  if (hash.startsWith("0xmock")) return <span className="whitespace-nowrap text-xs text-neutral-500">{label}: <span className="font-mono">mock {hash.slice(6, 12)}</span></span>;
  return <a className="whitespace-nowrap text-xs text-neutral-900 underline underline-offset-2 hover:text-neutral-600" href={`https://sepolia.etherscan.io/tx/${hash}`} target="_blank" rel="noreferrer">{label}: <span className="font-mono">{hash.slice(0, 10)}…</span> ↗</a>;
}

export function EnsLink({ name }: { name: string }) {
  return <a className="whitespace-nowrap font-mono text-sm text-neutral-900 underline underline-offset-2 hover:text-neutral-600" href={`https://sepolia.app.ens.domains/${name}`} target="_blank" rel="noreferrer">{name}</a>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-neutral-300 p-10 text-center text-sm text-neutral-500">{children}</div>;
}

export function PageTitle({ title, sub, action }: { title: string; sub?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3 border-b border-neutral-200 pb-4">
      <div className="min-w-0">
        <h1 className="text-2xl font-bold tracking-tight text-neutral-900">{title}</h1>
        {sub && <p className="mt-1 max-w-3xl text-sm text-neutral-500">{sub}</p>}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

export function BackLink({ href, children }: { href: string; children: React.ReactNode }) {
  return <Link href={href} className="inline-flex items-center gap-1 whitespace-nowrap text-sm text-neutral-500 hover:text-neutral-900">← {children}</Link>;
}

/* 金額と単位を切り離さない */
export function Amount({ value, unit = "USDC", className = "" }: { value: string; unit?: string; className?: string }) {
  return <span className={`whitespace-nowrap tabular-nums ${className}`}>{value}<span className="ml-1 text-[0.8em] font-normal text-neutral-500">{unit}</span></span>;
}

/* ---------- 種別タグ（絵文字の代わり。AI / 人 / 企業） ---------- */
export function Tag({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return <span className={`inline-flex shrink-0 items-center whitespace-nowrap rounded-sm border border-neutral-900 px-1 text-[10px] font-semibold leading-4 tracking-wide text-neutral-900 ${className}`}>{children}</span>;
}
export function KindTag({ kind }: { kind: "ai" | "human" | "company" | string }) {
  return <Tag>{kind === "human" ? "人" : kind === "company" ? "企業" : "AI"}</Tag>;
}
