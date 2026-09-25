"use client";

import { createContext, useCallback, useContext, useMemo, useState } from "react";
import { useAccount, useSignMessage } from "wagmi";
import { SiweMessage } from "siwe";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type AppConfig, type Me } from "./api";

type Auth = {
  me: Me | null;
  config: AppConfig | null;
  loading: boolean;
  signIn: () => Promise<void>;
  devLogin: (role: string) => Promise<void>;
  signOut: () => void;
  refresh: () => Promise<void>;
};

const Ctx = createContext<Auth>({ me: null, config: null, loading: true, signIn: async () => {}, devLogin: async () => {}, signOut: () => {}, refresh: async () => {} });

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return window.localStorage.getItem("choice.token"); } catch { return null; }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const { address, chainId } = useAccount();
  const { signMessageAsync } = useSignMessage();
  const qc = useQueryClient();
  const [token, setToken] = useState<string | null>(readToken);
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

  const signIn = useCallback(async () => {
    if (!address) throw new Error("先にウォレットを接続してください");
    const { nonce } = await api<{ nonce: string }>("/auth/nonce");
    const msg = new SiweMessage({
      domain: window.location.host, address, statement: "Sign in to Choice", uri: window.location.origin, version: "1",
      chainId: chainId ?? 11155111, nonce,
    });
    const message = msg.prepareMessage();
    const signature = await signMessageAsync({ message });
    const r = await api<{ token: string }>("/auth/verify", { method: "POST", json: { message, signature } });
    try { localStorage.setItem("choice.token", r.token); localStorage.removeItem("choice.dev"); } catch { /* ignore */ }
    setToken(r.token);
  }, [address, chainId, signMessageAsync]);

  const devLogin = useCallback(async (role: string) => {
    const r = await api<{ token: string }>("/auth/dev-login", { method: "POST", json: { role } });
    try { localStorage.setItem("choice.token", r.token); localStorage.setItem("choice.dev", "1"); } catch { /* ignore */ }
    setToken(r.token);
  }, []);

  const signOut = useCallback(() => {
    try { localStorage.removeItem("choice.token"); localStorage.removeItem("choice.dev"); } catch { /* ignore */ }
    setToken(null);
  }, []);

  const value = useMemo(() => ({ me, config: config ?? null, loading: !!token && isLoading, signIn, devLogin, signOut, refresh }), [me, config, token, isLoading, signIn, devLogin, signOut, refresh]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const useAuth = () => useContext(Ctx);
