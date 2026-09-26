"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ConnectButton } from "@rainbow-me/rainbowkit";
import { useAccount } from "wagmi";
import { useEffect, useRef, useState } from "react";
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
  { href: "/agents/mine", label: "Agent 管理" },
  { href: "/ens", label: "ENS" },
  { href: "/me", label: "マイページ" },
];
const OPS_NAV = { href: "/ops/jobs", label: "運用" };

/** 開発用: DEV_LOGIN_ENABLED のとき ?dev_login=<role> で自動ログイン（スクリーンショット・動作確認用） */
function DevAutoLogin() {
  const { me, devLogin } = useAuth();
  const { data: devUsers } = useQuery({ queryKey: ["dev-users"], queryFn: () => api<{ role: string; label: string }[]>("/auth/dev-users"), staleTime: Infinity });
  const done = useRef(false);
  useEffect(() => {
    const role = new URLSearchParams(window.location.search).get("dev_login");
    if (role && !me && !done.current && devUsers?.some((u) => u.role === role)) {
      done.current = true;
      void devLogin(role);
    }
  }, [me, devUsers, devLogin]);
  return null;
}

export function Header() {
  const path = usePathname();
  const { isConnected } = useAccount();
  const { me, signIn, devLogin, signOut, config } = useAuth();
  const { data: devUsers } = useQuery({ queryKey: ["dev-users"], queryFn: () => api<{ role: string; label: string }[]>("/auth/dev-users"), staleTime: Infinity });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const nav = me?.is_ops ? [...NAV, OPS_NAV] : NAV;

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
    <header className="sticky top-0 z-20 border-b border-neutral-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-8 w-8 place-items-center rounded-md bg-neutral-900 text-sm font-bold text-white">C</span>
          <span className="whitespace-nowrap font-semibold tracking-tight">Choice</span>
          <span className="hidden whitespace-nowrap text-xs text-neutral-400 xl:inline">AI Agent × World × ENS</span>
        </Link>
        <nav className="hidden min-w-0 items-center gap-1 overflow-x-auto md:flex">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={`whitespace-nowrap border-b-2 px-2.5 py-1.5 text-sm ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "border-neutral-900 font-medium text-neutral-900" : "border-transparent text-neutral-500 hover:text-neutral-900"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {mocks.length > 0 && <span className="hidden whitespace-nowrap rounded-sm border border-dashed border-neutral-400 px-2 py-1 text-[11px] text-neutral-600 md:inline" title="未設定の外部連携はモックで動作">mock: {mocks.join(", ")}</span>}
          <DevAutoLogin />
          <NotificationBell />
          <ConnectButton showBalance={false} chainStatus="icon" accountStatus="address" label="ウォレット接続" />
          {isConnected && !me && (
            <Button onClick={doSignIn} disabled={busy}>{busy ? "署名待ち…" : "Sign in"}</Button>
          )}
          {!me && devUsers && devUsers.length > 0 && (
            <select className="h-9 rounded-md border border-dashed border-neutral-900 bg-white px-2 text-xs text-neutral-900" value="" onChange={(e) => { if (e.target.value) void devLogin(e.target.value).catch((er) => setErr(String(er))); }} title="ウォレット不要のデモログイン（DEV_LOGIN_ENABLED）">
              <option value="">デモログイン</option>
              {devUsers.map((u) => <option key={u.role} value={u.role}>{u.label}</option>)}
            </select>
          )}
          {me && <span className="hidden max-w-32 truncate whitespace-nowrap text-xs text-neutral-500 xl:inline">{me.display_name ?? me.wallet_address.slice(0, 8)}</span>}
          {me && <Button variant="ghost" onClick={signOut} title={me.wallet_address}>Sign out</Button>}
        </div>
      </div>
      {err && <div className="mx-auto max-w-6xl px-4 pb-2 text-xs text-neutral-700">{err}</div>}
      <nav className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden">
        {nav.map((n) => (
          <Link key={n.href} href={n.href} className={`whitespace-nowrap rounded-sm border px-3 py-1 text-xs ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-700"}`}>{n.label}</Link>
        ))}
      </nav>
    </header>
  );
}
