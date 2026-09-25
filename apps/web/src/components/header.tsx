"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount } from "wagmi";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui";
import { NotificationBell } from "./notifications";

const NAV = [
  { href: "/", label: "Marketplace" },
  { href: "/cases", label: "案件" },
  { href: "/tasks", label: "Human Task" },
  { href: "/jury", label: "Jury" },
  { href: "/companies", label: "会社と人員" },
  { href: "/agents/mine", label: "My Agents" },
];

export function Header() {
  const path = usePathname();
  const { isConnected } = useAccount();
  const { me, signIn, devLogin, signOut, config } = useAuth();
  const { data: devUsers } = useQuery({ queryKey: ["dev-users"], queryFn: () => api<{ role: string; label: string }[]>("/auth/dev-users"), staleTime: Infinity });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const doSignIn = async () => {
    setBusy(true);
    setErr(null);
    try {
      await signIn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const mocks = config ? Object.entries(config.mock).filter(([, v]) => v).map(([k]) => k) : [];

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-6 px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-slate-900 text-sm font-bold text-white">C</span>
          <span className="font-semibold tracking-tight">Choice</span>
          <span className="hidden text-xs text-slate-400 sm:inline">AI Agent × World × ENS</span>
        </Link>
        <nav className="hidden items-center gap-1 md:flex">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href} className={`rounded-md px-3 py-1.5 text-sm ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "bg-slate-100 font-medium text-slate-900" : "text-slate-600 hover:text-slate-900"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          {mocks.length > 0 && <span className="hidden rounded-md bg-amber-50 px-2 py-1 text-[11px] text-amber-700 lg:inline" title="未設定の外部連携はモックで動作">mock: {mocks.join(", ")}</span>}
          <NotificationBell />
          <ConnectButton showBalance={false} chainStatus="icon" accountStatus="address" />
          {isConnected && !me && (
            <Button onClick={doSignIn} disabled={busy}>{busy ? "署名待ち…" : "Sign in"}</Button>
          )}
          {!me && devUsers && devUsers.length > 0 && (
            <select className="rounded-lg border border-dashed border-amber-400 bg-amber-50 px-2 py-2 text-xs text-amber-900" value="" onChange={(e) => { if (e.target.value) void devLogin(e.target.value).catch((er) => setErr(String(er))); }} title="ウォレット不要のデモログイン（DEV_LOGIN_ENABLED）">
              <option value="">デモログイン…</option>
              {devUsers.map((u) => <option key={u.role} value={u.role}>{u.label}</option>)}
            </select>
          )}
          {me && <span className="hidden text-xs text-slate-500 sm:inline">{me.display_name ?? me.wallet_address.slice(0, 8)}</span>}
          {me && <Button variant="ghost" onClick={signOut} title={me.wallet_address}>Sign out</Button>}
        </div>
      </div>
      {err && <div className="mx-auto max-w-6xl px-4 pb-2 text-xs text-rose-600">{err}</div>}
      <nav className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden">
        {NAV.map((n) => (
          <Link key={n.href} href={n.href} className="whitespace-nowrap rounded-md bg-slate-100 px-3 py-1 text-xs">{n.label}</Link>
        ))}
      </nav>
    </header>
  );
}
