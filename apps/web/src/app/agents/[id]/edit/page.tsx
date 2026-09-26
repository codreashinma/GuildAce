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
import { PolicyEditor, policyErrors, type PolicyDraft } from "@/components/policy-editor";

type Tx = { to: string; data: string; label: string };
type UpdateResult = { mode: "platform" | "creator"; changed_keys: string[]; ens?: "queued" | "mock" | "sign"; txs?: Tx[]; changed_subagents?: string[]; removed_subagents?: string[]; ens_subagents?: "queued" | "sign"; subagent_txs?: Tx[]; agent: Agent };

/** D4: Agent の編集。説明・ルール・利用料を更新し、ENS の text record を再書き込みする。
 *  platform 所有は worker（Owner 鍵）が書き、Creator 所有は Creator のウォレットで multicall に署名する。ラベルと公開先は変更不可。 */
export default function EditAgent() {
  const { id } = useParams<{ id: string }>();
  const { me } = useAuth();
  const { data: a } = useQuery({ queryKey: ["agent", id], queryFn: () => api<Agent>(`/agents/${id}`) });
  if (!me) return <p className="text-sm text-neutral-500">Please sign in.</p>;
  if (!a) return <p className="text-sm text-neutral-500">Loading…</p>;
  if (a.creator_id !== me.id) return <p className="text-sm text-neutral-500">Only the creator can edit this Agent.</p>;
  return <EditForm a={a} />;
}

function EditForm({ a }: { a: Agent }) {
  const router = useRouter();
  const { sendTransactionAsync } = useSendTransaction();
  const ensureSepolia = useEnsureSepolia();
  const pc = usePublicClient();
  const [f, setF] = useState(() => ({ name: a.name, description: a.description, category: a.category, rules: a.rules, fee_bps: a.fee_bps }));
  const [subs, setSubs] = useState<Subagent[]>(() => (a.subagents ?? []).map((x) => ({ ...x })));
  const [policy, setPolicy] = useState<PolicyDraft>(() => structuredClone(a.effective_policy));
  const policyChanged = JSON.stringify(policy) !== JSON.stringify(a.effective_policy); // 変えていなければ送らない（既定のままを保つ）
  const [err, setErr] = useState<unknown>(null);
  const [step, setStep] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const set = (k: string, v: string | number) => setF((s) => ({ ...s, [k]: v }));

  const save = async () => {
    setErr(null); setDone(null); setStep("Saving…");
    try {
      const r = await api<UpdateResult>(`/agents/${a.id}`, { method: "PATCH", json: { ...f, subagents: subs, policy: policyChanged ? { ...policy, domain: f.category } : null } });
      const txs = [...(r.ens === "sign" ? r.txs ?? [] : []), ...(r.ens_subagents === "sign" ? r.subagent_txs ?? [] : [])];
      if (txs.length) {
        await ensureSepolia();
        let last = "";
        for (const tx of txs) {
          setStep(`Sign ${tx.label}…`);
          const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
          setStep("Confirming transaction…");
          await pc!.waitForTransactionReceipt({ hash: h });
          last = h;
        }
        await api(`/agents/${a.id}/ens-written`, { method: "POST", json: { tx_hash: last } });
        setDone(`Updated ENS (${[...r.changed_keys, ...(r.changed_subagents ?? []).map((x) => `specialist: ${x}`)].join(", ")})`);
      } else if (r.ens === "queued" || r.ens_subagents === "queued") {
        setDone(`Saved. The Ops worker will write ENS (${[...r.changed_keys, ...(r.changed_subagents ?? []).map((x) => `specialist: ${x}`)].join(", ")}) within 1-2 minutes`);
      } else if (r.ens === "mock") {
        setDone("Saved (ENS write is mocked)");
      } else {
        setDone(r.changed_keys.length ? "Saved (not published, so nothing written to ENS)" : policyChanged ? "Saved (Steps and human usage are not written to ENS)" : "No changes");
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
      <BackLink href={`/agents/${a.id}`}>Agent details</BackLink>
      <PageTitle title="Edit PM Agent" sub="Only changed fields are rewritten to ENS text records. The label and publish target cannot be changed" />
      <Card className="space-y-4">
        <div className="text-xs text-neutral-500">ENS name <Mono className="text-neutral-900">{a.ens_name ?? `${a.label}.${a.parent_ens_name ?? "guildace.eth"}`}</Mono>{a.owner_mode === "creator" && <span className="ml-2">(Creator-owned: sign updates with your Wallet)</span>}</div>
        <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Description" hint="ENS: description"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category" hint="ENS: codrea.agent.category">
            <select className={inputCls} value={f.category} onChange={(e) => set("category", e.target.value)}>
              {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="Fee (%)" hint="ENS: codrea.agent.fee_bps">
            <input className={inputCls} type="number" min={0} max={50} step={0.5} value={f.fee_bps / 100} onChange={(e) => set("fee_bps", Math.round(Number(e.target.value) * 100))} />
          </Field>
        </div>
        <Field label="Approach & rules" hint="The PM Agent's system prompt. Not written to ENS"><textarea className={inputCls} rows={5} value={f.rules} onChange={(e) => set("rules", e.target.value)} /></Field>
        <SubagentsEditor value={subs} onChange={setSubs} published={a.status === "published"} defaultOpen agentEns={a.ens_name ?? `${a.label}.${a.parent_ens_name ?? "guildace.eth"}`} />
        <PolicyEditor value={policy} onChange={setPolicy} errors={policyErrors(err)} />
        {Object.keys(policyErrors(err)).length > 0 ? <p className="text-sm font-medium text-neutral-900">Please check the Steps / human usage inputs (items marked ⚠)</p> : <ErrorBox error={err} />}
        {done && <p className="text-sm text-neutral-900">{done}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={() => router.push(`/agents/${a.id}`)} disabled={!!step}>Back</Button>
          <Button onClick={save} disabled={!!step || !f.name || !!subagentsValid(subs)}>{step ?? "Save and update ENS"}</Button>
        </div>
      </Card>
    </div>
  );
}
