"use client";
import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePublicClient, useSendTransaction } from "wagmi";
import { Button } from "@/components/ui";
import { useEnsureSepolia } from "@/lib/chain";
import { api } from "@/lib/api";
import { Mono } from "@/components/ui";

/** GET /ens/resolve の結果。Sepolia の ENSv2 レジストリを .eth から辿った実値 */
export type EnsResolved = {
  name: string; configured: boolean; registered: boolean; source: string;
  owner?: string | null; registry?: string | null; subregistry?: string | null; resolver?: string | null; addr?: string | null; expiry?: number | null;
  texts?: Record<string, string>;
  wildcard?: { supported: boolean; checked_key: string | null; value: string | null; matches: boolean | null; error?: string };
};

export function useEnsResolve(name: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["ens-resolve", name],
    queryFn: () => api<EnsResolved>(`/ens/resolve?name=${encodeURIComponent(name!)}`),
    enabled: !!name && enabled,
    staleTime: 60_000,
    retry: 1,
  });
}

/** 任意の ENS 名の record を「ENS 上の値」として表示する。Agent 詳細・案件の project subname・人員で共用 */
export function EnsRecords({ name, keys, compact = false, title }: { name: string; keys?: string[]; compact?: boolean; title?: string }) {
  const { data, isLoading, error } = useEnsResolve(name);
  if (isLoading) return <p className="text-xs text-neutral-500">Reading from Sepolia…</p>;
  if (error) return <p className="text-xs text-neutral-700">Reading ENS failed</p>;
  if (!data || !data.configured) return <p className="text-xs text-neutral-500">ENS values can&apos;t be shown because RPC is not configured (Mock)</p>;
  if (!data.registered) return <p className="text-xs text-neutral-500"><Mono>{name}</Mono> is not registered on ENSv2 (Sepolia) yet</p>;
  const entries = Object.entries(data.texts ?? {}).filter(([k]) => !keys || keys.includes(k));
  return (
    <div className={compact ? "text-xs" : "text-sm"}>
      {title && <div className="mb-1 font-mono text-xs text-neutral-900">{title}</div>}
      <dl className="space-y-1">
        <div className="grid grid-cols-[7rem_1fr] gap-2"><dt className="text-xs leading-5 text-neutral-500">owner</dt><dd className="min-w-0"><Mono className="[overflow-wrap:anywhere] whitespace-normal">{data.owner ?? "-"}</Mono></dd></div>
        <div className="grid grid-cols-[7rem_1fr] gap-2"><dt className="text-xs leading-5 text-neutral-500">resolver</dt><dd className="min-w-0"><Mono className="[overflow-wrap:anywhere] whitespace-normal">{data.resolver ?? "-"}</Mono></dd></div>
        {data.subregistry && <div className="grid grid-cols-[7rem_1fr] gap-2"><dt className="text-xs leading-5 text-neutral-500">subregistry</dt><dd className="min-w-0"><Mono className="[overflow-wrap:anywhere] whitespace-normal">{data.subregistry}</Mono></dd></div>}
        {data.addr && <div className="grid grid-cols-[7rem_1fr] gap-2"><dt className="text-xs leading-5 text-neutral-500">addr</dt><dd className="min-w-0"><Mono className="[overflow-wrap:anywhere] whitespace-normal">{data.addr}</Mono></dd></div>}
        {entries.map(([k, v]) => (
          <div key={k} className="grid grid-cols-[7rem_1fr] gap-2 sm:grid-cols-[11rem_1fr]"><dt className="truncate font-mono text-xs leading-5 text-neutral-500" title={k}>{k}</dt><dd className="min-w-0 [overflow-wrap:anywhere]">{v}</dd></div>
        ))}
        {entries.length === 0 && <dd className="text-xs text-neutral-500">No text records yet</dd>}
      </dl>
    </div>
  );
}

export type EnsOwnerCheck = { name: string; configured: boolean; status: "unconfigured" | "unregistered" | "ok"; owner: string | null; is_mine: boolean | null; wallet?: string };
export type EnsReadiness = { name: string; configured: boolean; ready: boolean; registered: boolean; owner?: string | null; subregistry: string | null; resolver: string | null; missing: string[]; next_steps?: string[]; note?: string };

const NAME_RE = /^[a-z0-9-]+\.eth$/;

function useDebounced<T>(v: T, ms = 500) {
  const [d, setD] = useState(v);
  useEffect(() => { const t = setTimeout(() => setD(v), ms); return () => clearTimeout(t); }, [v, ms]);
  return d;
}

/** 入力中の .eth 名について「自分が所有しているか」「subname を発行できる状態か」を Sepolia で事前確認する（D1 / E1 共用）。
 *  onStatus には { ok } を返す。ok = 実チェーンで所有と準備が確認できた、または RPC 未設定（モック）で確認不能。 */
export function EnsNameCheck({ name, onStatus }: { name: string; onStatus?: (s: { ok: boolean; checking: boolean }) => void }) {
  const debounced = useDebounced(name.trim().toLowerCase());
  const valid = NAME_RE.test(debounced);
  const owner = useQuery({ queryKey: ["ens-check-owner", debounced], queryFn: () => api<EnsOwnerCheck>(`/ens/check-owner?name=${encodeURIComponent(debounced)}`), enabled: valid, staleTime: 30_000, retry: false });
  const ready = useQuery({ queryKey: ["ens-readiness", debounced], queryFn: () => api<EnsReadiness>(`/ens/readiness?name=${encodeURIComponent(debounced)}`), enabled: valid, staleTime: 30_000, retry: false });
  const checking = valid && (owner.isLoading || ready.isLoading);
  const unconfigured = owner.data?.configured === false;
  const ok = !!valid && !checking && (unconfigured || (!!owner.data?.is_mine && !!ready.data?.ready));
  useEffect(() => { onStatus?.({ ok, checking }); }, [ok, checking, onStatus]);
  if (!name) return null;
  if (!valid) return <p className="mt-1 text-xs text-neutral-500">Format: &lt;label&gt;.eth (lowercase letters, digits, hyphens)</p>;
  if (checking) return <p className="mt-1 text-xs text-neutral-500">Checking on Sepolia…</p>;
  if (owner.error || ready.error) return <p className="mt-1 text-xs text-neutral-700">Check failed ({String((owner.error ?? ready.error as Error)?.message ?? "")})</p>;
  if (unconfigured) return <p className="mt-1 text-xs text-neutral-500">Owner check skipped because RPC is not configured (Mock)</p>;
  const o = owner.data!; const r = ready.data!;
  return (
    <ul className="mt-1 space-y-0.5 text-xs">
      <li className={o.status === "ok" ? "text-neutral-900" : "text-neutral-700"}>{o.status === "unregistered" ? "✕ Not registered on ENSv2 (Sepolia)" : o.is_mine ? "✓ The connected Wallet is the Owner" : <>✕ Owned by a different address (<Mono>{o.owner}</Mono>)</>}</li>
      <li className={r.subregistry ? "text-neutral-900" : "text-neutral-700"}>{r.subregistry ? <>✓ Subregistry <Mono>{r.subregistry}</Mono></> : "✕ Subregistry not configured (cannot Issue subnames)"}</li>
      <li className={r.resolver ? "text-neutral-900" : "text-neutral-700"}>{r.resolver ? <>✓ Resolver <Mono>{r.resolver}</Mono></> : "✕ Resolver not configured (cannot write Records)"}</li>
      {r.next_steps?.map((s) => <li key={s} className="text-neutral-500">→ {s}</li>)}
      {o.is_mine && !r.ready && r.registered && <li className="pt-1"><EnsSetupButton name={debounced} /></li>}
      {o.status === "unregistered" && <li className="pt-1"><EnsRegisterButton name={debounced} /></li>}
    </ul>
  );
}

type SetupCalldata = { mock: boolean; ready: boolean; txs: { to: string; data: string; label: string }[]; resolver?: { address: string; exists: boolean }; subregistry?: { address: string; exists: boolean } };

/** 名前の所有者が自分のウォレットで OwnedResolver / UserRegistry を用意する（API は calldata を返すだけ。鍵は使わない） */
export function EnsSetupButton({ name, onDone }: { name: string; onDone?: () => void }) {
  const qc = useQueryClient();
  const { sendTransactionAsync } = useSendTransaction();
  const ensureSepolia = useEnsureSepolia();
  const pc = usePublicClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setErr(null);
    try {
      setBusy("Fetching setup steps…");
      const r = await api<SetupCalldata>(`/ens/setup-calldata?name=${encodeURIComponent(name)}`);
      if (r.txs.length) await ensureSepolia();
      for (const tx of r.txs) {
        setBusy(`Sign ${tx.label}…`);
        const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
        setBusy("Confirming transaction…");
        await pc!.waitForTransactionReceipt({ hash: h });
      }
      await qc.invalidateQueries({ queryKey: ["ens-readiness", name] });
      await qc.invalidateQueries({ queryKey: ["ens-resolve", name] });
      onDone?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <span className="inline-flex flex-col gap-1">
      <Button variant="secondary" className="px-2 py-1 text-xs" disabled={!!busy} onClick={run}>{busy ?? "Set up Resolver and Subregistry with my Wallet"}</Button>
      {err && <span className="max-w-md text-[11px] text-neutral-700 [overflow-wrap:anywhere]">{err}</span>}
    </span>
  );
}


type RegisterCalldata = { mock: boolean; txs: { to: string; data: string; label: string }[]; secret?: string; price?: string; min_commitment_age?: number };

/** 利用者が自分のウォレットで .eth（2LD）を登録する: commit → 60 秒待機 → register → リゾルバとサブレジストリの準備。
 *  API は calldata を返すだけで鍵を持たない。登録料は ENSv2 beta のテスト用トークン（誰でも mint 可）。 */
export function EnsRegisterButton({ name }: { name: string }) {
  const qc = useQueryClient();
  const { sendTransactionAsync } = useSendTransaction();
  const ensureSepolia = useEnsureSepolia();
  const pc = usePublicClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const sendAll = async (txs: { to: string; data: string; label: string }[], prefix: string) => {
    for (const tx of txs) {
      setBusy(`${prefix}Sign ${tx.label.replace(/ →.*$/, "")}…`);
      const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
      setBusy(`${prefix}Confirming transaction…`);
      await pc!.waitForTransactionReceipt({ hash: h });
    }
  };
  const run = async () => {
    setErr(null);
    try {
      await ensureSepolia();
      setBusy("Fetching registration details…");
      const c = await api<RegisterCalldata>(`/ens/register-calldata?name=${encodeURIComponent(name)}&phase=commit`);
      if (c.mock) { setBusy(null); return; }
      await sendAll(c.txs, "1/3 ");
      const wait = (c.min_commitment_age ?? 60) + 10;
      for (let i = wait; i > 0; i--) { setBusy(`2/3 Waiting to prevent front-running… ${i}s (don't close this page)`); await new Promise((r) => setTimeout(r, 1000)); }
      const r = await api<RegisterCalldata>(`/ens/register-calldata?name=${encodeURIComponent(name)}&phase=register&secret=${c.secret}`);
      await sendAll(r.txs, "2/3 ");
      setBusy("3/3 Setting up Resolver and Subregistry…");
      const su = await api<SetupCalldata>(`/ens/setup-calldata?name=${encodeURIComponent(name)}`);
      await sendAll(su.txs, "3/3 ");
      await qc.invalidateQueries({ queryKey: ["ens-check-owner", name] });
      await qc.invalidateQueries({ queryKey: ["ens-readiness", name] });
      await qc.invalidateQueries({ queryKey: ["ens-resolve", name] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  return (
    <span className="inline-flex flex-col gap-1">
      <Button variant="secondary" className="px-2 py-1 text-xs" disabled={!!busy} onClick={run}>{busy ?? `Register ${name} with my Wallet (test tokens, ~8 txs, 60s wait)`}</Button>
      {err && <span className="max-w-md text-[11px] text-neutral-700 [overflow-wrap:anywhere]">{err}</span>}
    </span>
  );
}
