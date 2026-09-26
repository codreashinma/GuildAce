"use client";

import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { usePublicClient, useSendTransaction } from "wagmi";
import { api, CATEGORY_LABEL, type Agent, type Subagent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEnsureSepolia } from "@/lib/chain";
import { BackLink, Button, Card, ErrorBox, Field, inputCls, Mono, PageTitle } from "@/components/ui";
import { SubagentsEditor, subagentsValid } from "@/components/subagent-rules";

type Tx = { to: string; data: string; label: string };
type UpdateResult = { mode: "platform" | "creator"; changed_keys: string[]; ens?: "queued" | "mock" | "sign"; txs?: Tx[]; changed_subagents?: string[]; removed_subagents?: string[]; ens_subagents?: "queued" | "sign"; subagent_txs?: Tx[]; agent: Agent };

/** D4: Agent の編集。説明・ルール・利用料を更新し、ENS の text record を再書き込みする。
 *  platform 所有は worker（Owner 鍵）が書き、Creator 所有は Creator のウォレットで multicall に署名する。ラベルと公開先は変更不可。 */
export default function EditAgent() {
  const { id } = useParams<{ id: string }>();
  const { me } = useAuth();
  const { data: a } = useQuery({ queryKey: ["agent", id], queryFn: () => api<Agent>(`/agents/${id}`) });
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  if (!a) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  if (a.creator_id !== me.id) return <p className="text-sm text-neutral-500">作成者のみ編集できます。</p>;
  return <EditForm a={a} />;
}

function EditForm({ a }: { a: Agent }) {
  const router = useRouter();
  const { sendTransactionAsync } = useSendTransaction();
  const ensureSepolia = useEnsureSepolia();
  const pc = usePublicClient();
  const [f, setF] = useState(() => ({ name: a.name, description: a.description, category: a.category, rules: a.rules, fee_bps: a.fee_bps }));
  const [subs, setSubs] = useState<Subagent[]>(() => (a.subagents ?? []).map((x) => ({ ...x })));
  const [err, setErr] = useState<unknown>(null);
  const [step, setStep] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const set = (k: string, v: string | number) => setF((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setErr(null); setDone(null); setStep("保存中…");
    try {
      const r = await api<UpdateResult>(`/agents/${a.id}`, { method: "PATCH", json: { ...f, subagents: subs } });
      const txs = [...(r.ens === "sign" ? r.txs ?? [] : []), ...(r.ens_subagents === "sign" ? r.subagent_txs ?? [] : [])];
      if (txs.length) {
        await ensureSepolia();
        let last = "";
        for (const tx of txs) {
          setStep(`${tx.label} に署名…`);
          const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
          setStep("トランザクション確認中…");
          await pc!.waitForTransactionReceipt({ hash: h });
          last = h;
        }
        await api(`/agents/${a.id}/ens-written`, { method: "POST", json: { tx_hash: last } });
        setDone(`ENS を更新しました（${[...r.changed_keys, ...(r.changed_subagents ?? []).map((x) => `専門: ${x}`)].join(", ")}）`);
      } else if (r.ens === "queued" || r.ens_subagents === "queued") {
        setDone(`保存しました。ENS（${[...r.changed_keys, ...(r.changed_subagents ?? []).map((x) => `専門: ${x}`)].join(", ")}）は運用ワーカーが 1〜2 分で書き込みます`);
      } else if (r.ens === "mock") {
        setDone("保存しました（ENS 書き込みはモック）");
      } else {
        setDone(r.changed_keys.length ? "保存しました（未公開のため ENS 書き込みなし）" : "変更はありません");
      }
      setTimeout(() => router.push(`/agents/${a.id}`), 1200);
    } catch (e) {
      setErr(e);
    } finally {
      setStep(null);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <BackLink href={`/agents/${a.id}`}>Agent 詳細</BackLink>
      <PageTitle title="PM Agent を編集" sub="変更した項目だけ ENS の text record を再書き込みします。ラベルと公開先は変更できません" />
      <Card className="space-y-4">
        <div className="text-xs text-neutral-500">ENS 名 <Mono className="text-neutral-900">{a.ens_name ?? `${a.label}.${a.parent_ens_name ?? "choice.eth"}`}</Mono>{a.owner_mode === "creator" && <span className="ml-2">（Creator 所有: 更新はあなたのウォレットで署名）</span>}</div>
        <Field label="名前"><input className={inputCls} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="説明" hint="ENS: description"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="カテゴリ" hint="ENS: codrea.agent.category">
            <select className={inputCls} value={f.category} onChange={(e) => set("category", e.target.value)}>
              {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="利用料（%）" hint="ENS: codrea.agent.fee_bps">
            <input className={inputCls} type="number" min={0} max={50} step={0.5} value={f.fee_bps / 100} onChange={(e) => set("fee_bps", Math.round(Number(e.target.value) * 100))} />
          </Field>
        </div>
        <Field label="進め方・ルール" hint="PM Agent の system prompt。ENS には書きません"><textarea className={inputCls} rows={5} value={f.rules} onChange={(e) => set("rules", e.target.value)} /></Field>
        <SubagentsEditor value={subs} onChange={setSubs} published={a.status === "published"} defaultOpen agentEns={a.ens_name ?? `${a.label}.${a.parent_ens_name ?? "choice.eth"}`} />
        <ErrorBox error={err} />
        {done && <p className="text-sm text-neutral-900">{done}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => router.push(`/agents/${a.id}`)} disabled={!!step}>戻る</Button>
          <Button onClick={save} disabled={!!step || !f.name || !!subagentsValid(subs)}>{step ?? "保存して ENS を更新"}</Button>
        </div>
      </Card>
    </div>
  );
}
