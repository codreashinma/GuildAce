"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useAccount, useAccountEffect, useSignMessage } from "wagmi";
import { SiweMessage } from "siwe";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AppConfig, type Me } from "./api";

type Auth = {
  me: Me | null;
  config: AppConfig | null;
  /** デモログイン（秘密鍵の無い合成アドレス）でログイン中。実チェーンの署名はできない */
  dev: boolean;
  loading: boolean;
  /** role = ウォレット接続の前に選んだ利用者種別（ログインしたアカウントに保存される） */
  signIn: (role?: string) => Promise<void>;
  devLogin: (role: string) => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<Auth>({ me: null, config: null, dev: false, loading: true, signIn: async () => {}, devLogin: async () => {}, signOut: () => {}, refresh: async () => {} });

function readDev(): boolean {
  if (typeof window === "undefined") return false;
  try { return window.localStorage.getItem("choice.dev") === "1"; } catch { return false; }
}

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage.getItem("choice.token"); } catch { return null; }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { address, chainId } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(readToken);
  const [dev, setDev] = useState<boolean>(readDev);
  const { data: config } = useQuery({ queryKey: ["config"], queryFn: () => api<AppConfig>("/config"), staleTime: 60_000 });
  const { data: fetched, isLoading } = useQuery({
    queryKey: ["me", token],
    queryFn: async () => { try { return await api<Me>("/auth/me"); } catch { return null; } },
    enabled: !!token,
  });

  // 別のウォレットに切り替わっていたらログイン状態を無効化する
  const me = useMemo(() => {
    if (!token || !fetched) return null;
    let dev = false;
    try { dev = localStorage.getItem("choice.dev") === "1"; } catch { /* ignore */ }
    if (!dev && address && fetched.wallet_address !== address.toLowerCase()) return null;
    return fetched;
  }, [token, fetched, address]);

  const refresh = useCallback(async () => { await qc.invalidateQueries({ queryKey: ["me"] }); }, [qc]);

  const signIn = useCallback(async (role?: string) => {
    if (!address) throw new Error("Please connect your wallet first");
    const { nonce } = await api<{ nonce: string }>("/auth/nonce");
    const msg = new SiweMessage({
      domain: window.location.host, address, statement: "Sign in to Choice", uri: window.location.origin, version: "1",
      chainId: chainId ?? 11155111, nonce,
    });
    const message = msg.prepareMessage();
    const signature = await signMessageAsync({ message });
    const r = await api<{ token: string }>("/auth/verify", { method: "POST", json: { message, signature, role } });
    try { localStorage.setItem("choice.token", r.token); localStorage.removeItem("choice.dev"); } catch { /* ignore */ }
    setDev(false);
    setToken(r.token);
  }, [address, chainId, signMessageAsync]);

  const devLogin = useCallback(async (role: string) => {
    const r = await api<{ token: string }>("/auth/dev-login", { method: "POST", json: { role } });
    try { localStorage.setItem("choice.token", r.token); localStorage.setItem("choice.dev", "1"); } catch { /* ignore */ }
    setDev(true);
    setToken(r.token);
  }, []);

  const signOut = useCallback(() => {
    try { localStorage.removeItem("choice.token"); localStorage.removeItem("choice.dev"); } catch { /* ignore */ }
    setDev(false);
    setToken(null);
  }, []);

  // ウォレットを切断したらサインアウトする（デモアカウントはウォレットを使わないので対象外）
  useAccountEffect({ onDisconnect: () => { if (!readDev()) signOut(); } });

  const value = useMemo(() => ({ me, config: config ?? null, dev: dev && !!me, loading: !!token && isLoading, signIn, devLogin, signOut, refresh }), [me, config, dev, token, isLoading, signIn, devLogin, signOut, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
