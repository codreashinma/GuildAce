"use client";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { ConnectButton, useConnectModal } from "@rainbow-me/rainbowkit";
import { useAccount } from "wagmi";
import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type UserRole } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui";
import { NotificationBell } from "./notifications";

// auth: 未ログインでは「Sign in してください」しか出ないページ。未ログインのときはメニューに出さない
const NAV = [
  { href: "/", label: "Marketplace" },
  { href: "/cases", label: "案件", auth: true },
  { href: "/tasks", label: "Human Task" },
  { href: "/jury", label: "Jury" },
  { href: "/companies", label: "会社と人員", auth: true },
  { href: "/agents/mine", label: "Agent 管理", auth: true },
  { href: "/ens", label: "ENS" },
  { href: "/me", label: "マイページ", auth: true },
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

type DevUser = { role: string; label: string; type: string };
/** 利用者種別の一覧の先頭に出す、ウォレット不要のデモアカウント（API の種別ではない） */
const DEMO_ROLE: UserRole = { role: "demo", label: "デモアカウント" };

/** 未ログイン時の入口。先に利用者種別を選び、次に接続する。
 * 「ウォレットで接続」は接続 → SIWE 署名まで続けて進め、選んだ種別をアカウントに保存する。
 * 種別「デモアカウント」（DEV_LOGIN_ENABLED のときだけ）はウォレット不要の固定アカウントを選んで入る */
function LoginMenu({ onError }: { onError: (msg: string | null) => void }) {
  const { isConnected } = useAccount();
  const { openConnectModal } = useConnectModal();
  const { signIn, devLogin } = useAuth();
  const { data: roles } = useQuery({ queryKey: ["user-roles"], queryFn: () => api<UserRole[]>("/auth/roles"), staleTime: Infinity });
  const { data: devUsers } = useQuery({ queryKey: ["dev-users"], queryFn: () => api<DevUser[]>("/auth/dev-users"), staleTime: Infinity });
  const [open, setOpen] = useState(false);
  const [role, setRole] = useState<UserRole | null>(null);
  const [busy, setBusy] = useState(false);
  // ウォレットで接続を押した後だけ自動で署名に進む（Sign out 直後や再読み込み時に勝手に署名を求めない）。値は選んだ種別
  const pending = useRef<string | null>(null);

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    onError(null);
    try {
      await fn();
    } catch (e) {
      onError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (pending.current && isConnected) {
      const r = pending.current;
      pending.current = null;
      void run(() => signIn(r));
    }
  }, [isConnected, signIn]); // eslint-disable-line react-hooks/exhaustive-deps

  const close = () => { setOpen(false); setRole(null); };

  const withWallet = (r: string) => {
    close();
    if (isConnected) {
      void run(() => signIn(r));
    } else {
      pending.current = r;
      openConnectModal?.();
    }
  };

  const demo = role?.role === DEMO_ROLE.role;
  const item = "w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-neutral-100";

  return (
    <div className="relative">
      <Button variant="inverse" onClick={() => (open ? close() : setOpen(true))} disabled={busy}>{busy ? "署名待ち…" : "ウォレット接続"}</Button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={close} />
          <div className="absolute right-0 z-20 mt-2 w-64 rounded-md border border-neutral-900 bg-white p-2 text-neutral-900 shadow-[4px_4px_0_0_#171717]">
            {!role ? (
              <>
                <div className="px-2 pb-1 pt-1 text-xs font-semibold text-neutral-500">1. 利用者種別を選ぶ</div>
                {[...(devUsers && devUsers.length > 0 ? [DEMO_ROLE] : []), ...(roles ?? [])].map((r) => (
                  <button key={r.role} onClick={() => setRole(r)} className={item}>{r.label}</button>
                ))}
              </>
            ) : (
              <>
                <div className="flex items-center justify-between px-2 pb-1 pt-1 text-xs font-semibold text-neutral-500">
                  <span>{demo ? "2. デモアカウントを選ぶ" : `2. ${role.label}として接続`}</span>
                  <button onClick={() => setRole(null)} className="font-normal underline">種別を変える</button>
                </div>
                {demo ? (devUsers ?? []).map((u) => (
                  <button key={u.role} onClick={() => { close(); void run(() => devLogin(u.role)); }} className={item}>{u.label}</button>
                )) : (
                  <button onClick={() => withWallet(role.role)} className={`${item} font-medium`}>
                    {isConnected ? "署名してログイン" : "ウォレットで接続"}
                  </button>
                )}
              </>
            )}
          </div>
        </>
      )}
    </div>
  );
}

export function Header() {
  const path = usePathname();
  const { me, dev, signOut, config } = useAuth();
  const [err, setErr] = useState<string | null>(null);
  const nav = me ? (me.is_ops ? [...NAV, OPS_NAV] : NAV) : NAV.filter((n) => !n.auth);

  const mocks = config ? Object.entries(config.mock).filter(([, v]) => v).map(([k]) => k) : [];

  return (
    <header className="sticky top-0 z-20 border-b border-neutral-800 bg-black text-white">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3">
        <Link href="/" className="flex shrink-0 items-center">
          {/* 白抜き・透過のロゴ（黒いヘッダー用）。6KB の PNG なので画像最適化（/_next/image）を通さずそのまま配信する */}
          <Image src="/logo.png" alt="GuildAce" width={514} height={145} priority unoptimized className="h-auto w-[100px]" />
        </Link>
        <nav className="hidden min-w-0 items-center gap-1 overflow-x-auto md:flex">
          {nav.map((n) => (
            <Link key={n.href} href={n.href} className={`whitespace-nowrap border-b-2 px-2.5 py-1.5 text-sm ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "border-white font-medium text-white" : "border-transparent text-neutral-400 hover:text-white"}`}>
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          {mocks.length > 0 && <span className="hidden whitespace-nowrap rounded-sm border border-dashed border-neutral-500 px-2 py-1 text-[11px] text-neutral-300 md:inline" title="未設定の外部連携はモックで動作">mock: {mocks.join(", ")}</span>}
          <DevAutoLogin />
          <NotificationBell />
          {!me && <LoginMenu onError={setErr} />}
          {me && !dev && <ConnectButton showBalance={false} chainStatus="icon" accountStatus="address" />}
          {me && dev && <span className="whitespace-nowrap rounded-sm border border-dashed border-neutral-500 px-2 py-1 text-xs text-neutral-300" title="ウォレット不要のデモアカウント（チェーンへの署名はできない）">デモ: {me.display_name}</span>}
          {/* ウォレットのログインは切断 = サインアウト（lib/auth）なので、Sign out はウォレットを使わないデモアカウントだけに出す */}
          {me && dev && <Button variant="outline-inverse" onClick={signOut}>Sign out</Button>}
        </div>
      </div>
      {err && <div className="mx-auto max-w-6xl px-4 pb-2 text-xs text-neutral-300">{err}</div>}
      <nav className="flex gap-1 overflow-x-auto px-4 pb-2 md:hidden">
        {nav.map((n) => (
          <Link key={n.href} href={n.href} className={`whitespace-nowrap rounded-sm border px-3 py-1 text-xs ${path === n.href || (n.href !== "/" && path.startsWith(n.href)) ? "border-white bg-white text-neutral-900" : "border-neutral-700 text-neutral-300"}`}>{n.label}</Link>
        ))}
      </nav>
    </header>
  );
}
