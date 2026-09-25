"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { usePublicClient, useSendTransaction } from "wagmi";
import { api, short, type Company, type Member } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Badge, Button, Card, Empty, ErrorBox, Field, inputCls, Mono, PageTitle, TxLink } from "@/components/ui";

/** F9: 受注側の会社が、自社の .eth の下に人員を登録する。PM Agent はここから Human Task を指名する */
export default function Companies() {
  const { me, config } = useAuth();
  const qc = useQueryClient();
  const { data: mine } = useQuery({ queryKey: ["companies", "mine", me?.id], queryFn: () => api<Company[]>("/companies/mine"), enabled: !!me });
  const { data: all } = useQuery({ queryKey: ["companies"], queryFn: () => api<Company[]>("/companies") });
  const [f, setF] = useState({ name: "", ens_name: "", description: "" });
  const [err, setErr] = useState<unknown>(null);
  const create = useMutation({
    mutationFn: () => api<Company>("/companies", { method: "POST", json: f }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["companies"] }); setF({ name: "", ens_name: "", description: "" }); setErr(null); },
    onError: setErr,
  });
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;

  return (
    <div className="space-y-8">
      <PageTitle title="会社と人員" sub="会社が所有する .eth の下に人員を subname として登録します。PM Agent は ENS のレコード（役割・スキル・拠点・稼働可否）を見て Human Task を指名します" />

      {mine?.map((c) => <CompanyCard key={c.id} c={c} mock={!config || !!config.mock.chain} />)}

      <Card className="space-y-3">
        <h2 className="font-semibold">会社を登録</h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="会社名"><input className={inputCls} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="ENS 名（会社が所有する .eth）" hint="接続ウォレットが所有者であることを ENSv2 で確認します（RPC 未設定時はモック）"><input className={inputCls} placeholder="field-co.eth" value={f.ens_name} onChange={(e) => setF({ ...f, ens_name: e.target.value.toLowerCase() })} /></Field>
        </div>
        <Field label="説明"><input className={inputCls} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <ErrorBox error={err} />
        <div className="flex justify-end"><Button disabled={!f.name || !f.ens_name || create.isPending} onClick={() => create.mutate()}>登録</Button></div>
      </Card>

      <div>
        <h2 className="mb-3 font-semibold">登録されている会社 <span className="text-xs font-normal text-neutral-500">PM Agent の指名候補になる人員プール</span></h2>
        {!all?.length ? <Empty>まだ会社がありません</Empty> : (
          <div className="grid gap-3 sm:grid-cols-2">
            {all.map((c) => (
              <Card key={c.id}>
                <div className="flex flex-wrap items-center gap-2"><b className="whitespace-nowrap">{c.name}</b><Mono className="text-neutral-900">{c.ens_name}</Mono>{c.ens_verified && <Badge status="published">所有確認済</Badge>}</div>
                <p className="mt-1 text-xs text-neutral-500">{c.description}</p>
                <ul className="mt-2 space-y-1 text-xs">{c.members.map((m) => <li key={m.id} className="flex flex-wrap items-center gap-x-2 gap-y-0.5"><Mono className="text-neutral-900">{m.ens_name}</Mono><span className="whitespace-nowrap">{m.role}</span><span className="text-neutral-500">{m.skills}</span><span className="whitespace-nowrap text-neutral-500">{m.location}</span>{!m.available && <Badge>稼働不可</Badge>}</li>)}</ul>
              </Card>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function CompanyCard({ c, mock }: { c: Company; mock: boolean }) {
  const qc = useQueryClient();
  const [m, setM] = useState({ label: "", name: "", wallet_address: "", role: "", skills: "", location: "", available: true });
  const [err, setErr] = useState<unknown>(null);
  const add = useMutation({
    mutationFn: () => api<Member>(`/companies/${c.id}/members`, { method: "POST", json: m }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["companies"] }); setM({ label: "", name: "", wallet_address: "", role: "", skills: "", location: "", available: true }); setErr(null); },
    onError: setErr,
  });
  const toggle = useMutation({
    mutationFn: (x: Member) => api(`/companies/${c.id}/members/${x.id}`, { method: "PATCH", json: { available: !x.available } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["companies"] }),
  });
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="whitespace-nowrap font-semibold">{c.name}</h2><Mono className="text-sm text-neutral-900">{c.ens_name}</Mono>
        <Badge status={c.ens_verified ? "published" : "draft"}>{c.ens_verified ? "ENS 所有確認済" : "所有未確認（モック）"}</Badge>
        <span className="whitespace-nowrap text-xs text-neutral-500">管理者 <Mono>{short(c.admin.wallet_address)}</Mono></span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">ENS 名</th><th className="pr-3">名前 / 役割</th><th className="pr-3">スキル</th><th className="pr-3">拠点</th><th className="pr-3">稼働</th><th>ENS 書き込み</th></tr></thead>
          <tbody>
            {c.members.map((x) => (
              <tr key={x.id} className="border-t border-neutral-100 align-middle [&>td]:py-2 [&>td]:pr-3">
                <td><Mono className="text-neutral-900">{x.ens_name}</Mono></td>
                <td className="whitespace-nowrap">{x.name} <span className="text-xs text-neutral-500">{x.role}</span></td>
                <td className="text-xs">{x.skills}</td><td className="whitespace-nowrap text-xs">{x.location}</td>
                <td><button className={`whitespace-nowrap rounded-sm border px-2 py-0.5 text-xs ${x.available ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-300 text-neutral-500"}`} onClick={() => toggle.mutate(x)}>{x.available ? "稼働可" : "稼働不可"}</button></td>
                <td><EnsWrite c={c} m={x} mock={mock} /></td>
              </tr>
            ))}
            {c.members.length === 0 && <tr><td colSpan={6} className="py-3 text-center text-xs text-neutral-500">人員がまだいません</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="rounded-md border border-dashed border-neutral-300 p-3">
        <div className="mb-2 text-sm font-medium">人員を追加</div>
        <div className="grid gap-2 sm:grid-cols-3">
          <input className={inputCls} placeholder={`ラベル（例 dan → dan.${c.ens_name}）`} value={m.label} onChange={(e) => setM({ ...m, label: e.target.value.toLowerCase() })} />
          <input className={inputCls} placeholder="表示名" value={m.name} onChange={(e) => setM({ ...m, name: e.target.value })} />
          <input className={inputCls} placeholder="ウォレット 0x…" value={m.wallet_address} onChange={(e) => setM({ ...m, wallet_address: e.target.value })} />
          <input className={inputCls} placeholder="役割（photographer など）" value={m.role} onChange={(e) => setM({ ...m, role: e.target.value })} />
          <input className={inputCls} placeholder="スキル（カンマ区切り）" value={m.skills} onChange={(e) => setM({ ...m, skills: e.target.value })} />
          <input className={inputCls} placeholder="拠点" value={m.location} onChange={(e) => setM({ ...m, location: e.target.value })} />
        </div>
        <ErrorBox error={err} />
        <div className="mt-2 flex justify-end"><Button disabled={!m.label || !m.name || !m.wallet_address || add.isPending} onClick={() => add.mutate()}>追加</Button></div>
      </div>
    </Card>
  );
}

/** 会社管理者のウォレットで subname 発行と record 書き込みの tx を送る */
function EnsWrite({ c, m, mock }: { c: Company; m: Member; mock: boolean }) {
  const qc = useQueryClient();
  const { sendTransactionAsync } = useSendTransaction();
  const pc = usePublicClient();
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const run = async () => {
    setErr(null);
    try {
      let last = "0x" + Array.from(crypto.getRandomValues(new Uint8Array(32))).map((b) => b.toString(16).padStart(2, "0")).join("");
      if (!mock) {
        const r = await api<{ mock: boolean; txs: { to: string; data: string; label: string }[] }>(`/companies/${c.id}/members/${m.id}/ens-calldata`);
        for (const tx of r.txs) {
          setBusy(tx.label);
          const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
          await pc!.waitForTransactionReceipt({ hash: h });
          last = h;
        }
      }
      await api(`/companies/${c.id}/members/${m.id}/ens-written`, { method: "POST", json: { tx_hash: last } });
      qc.invalidateQueries({ queryKey: ["companies"] });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  if (m.ens_status === "written") return <span className="inline-flex flex-wrap items-center gap-2 whitespace-nowrap text-xs text-neutral-900">書き込み済 <TxLink hash={m.ens_tx_hash} /></span>;
  return (
    <div className="flex flex-col gap-1">
      <Button variant="secondary" className="px-2 py-1 text-xs" disabled={!!busy} onClick={run}>{busy ?? (mock ? "ENS に書き込む（モック）" : "ENS に書き込む")}</Button>
      {err && <span className="max-w-xs text-[11px] text-neutral-700">{err}</span>}
    </div>
  );
}
