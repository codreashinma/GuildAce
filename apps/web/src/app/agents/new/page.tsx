"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { DEFAULT_SUBAGENTS, api, CATEGORY_LABEL, type Agent, type Subagent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Field, inputCls, PageTitle } from "@/components/ui";
import { usePublishAgent } from "@/components/publish-agent";
import { SubagentsEditor, subagentsValid } from "@/components/subagent-rules";
import { EnsNameCheck } from "@/components/ens-records";
import { defaultPolicy, PolicyEditor, policyErrors, type PolicyDraft } from "@/components/policy-editor";

export default function NewAgent() {
  const router = useRouter();
  const { me, config } = useAuth();
  const [f, setF] = useState({ name: "Web Dev PM Agent", label: "", description: "", category: "web", rules: "", fee_bps: 200, payout_address: "" });
  const [subs, setSubs] = useState<Subagent[]>(() => DEFAULT_SUBAGENTS.map((x) => ({ ...x })));
  const [mode, setMode] = useState<"platform" | "creator">("platform");
  const [ownName, setOwnName] = useState("");
  const [ownOk, setOwnOk] = useState<{ ok: boolean; checking: boolean }>({ ok: false, checking: false });
  const [subagents, setSubagents] = useState(true);
  const onOwnStatus = useCallback((s: { ok: boolean; checking: boolean }) => setOwnOk(s), []);
  const [policy, setPolicy] = useState<PolicyDraft>(() => defaultPolicy("web"));
  const [policyTouched, setPolicyTouched] = useState(false); // 触っていなければ送らない（= 既定の policy。DEC-002）
  const [err, setErr] = useState<unknown>(null);
  const [failedPublish, setFailedPublish] = useState(false);
  const [busy, setBusy] = useState(false);
  const { publish: doPublish, step } = usePublishAgent();
  const set = (k: string, v: string | number) => setF((s) => ({ ...s, [k]: v }));

  const submit = async (publish: boolean) => {
    setErr(null);
    setBusy(true);
    try {
      const a = await api<Agent>("/agents", { method: "POST", json: { ...f, payout_address: f.payout_address || null, parent_ens_name: mode === "creator" ? ownName : null, subagents: subs,
        policy: policyTouched ? { ...policy, domain: f.category } : null,
      } });
      if (publish) await doPublish(a.id, { subagents });
      router.push(`/agents/${a.id}`);
    } catch (e) {
      setErr(e);
      setFailedPublish(publish && mode === "creator");
    } finally {
      setBusy(false);
    }
  };

  if (!me) return <p className="text-sm text-neutral-500">Connect your Wallet and sign in.</p>;
  const parent = mode === "creator" ? (ownName || "<your-name>.eth") : (config?.ens_parent_name ?? "guildace.eth");
  const ens = `${f.label || "<PM Agent label>"}.${parent}`;
  const pErrs = policyErrors(err);

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="Create PM Agent" sub="Your Agent is published as an ENS subname and earns a fee every time it is used" />
      <Card className="space-y-4">
        <Field label="Name"><input className={inputCls} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="Publish under (ENS parent name)" hint="If placed under the Creator's own .eth, the Creator becomes the Owner of the name and signs the Issue and Record writes with their own Wallet">
          <div className="grid gap-2 sm:grid-cols-2">
            <button type="button" onClick={() => setMode("platform")} className={`rounded-md border p-3 text-left text-sm ${mode === "platform" ? "border-neutral-900 shadow-[2px_2px_0_0_#171717]" : "border-neutral-300"}`}>
              <div className="font-medium">Platform parent name</div><div className="mt-0.5 font-mono text-xs text-neutral-600">&lt;label&gt;.{config?.ens_parent_name ?? "guildace.eth"}</div><div className="mt-1 text-xs text-neutral-500">No Wallet signature needed. Issued by the Ops wallet</div>
            </button>
            <button type="button" onClick={() => setMode("creator")} className={`rounded-md border p-3 text-left text-sm ${mode === "creator" ? "border-neutral-900 shadow-[2px_2px_0_0_#171717]" : "border-neutral-300"}`}>
              <div className="font-medium">Under my own ENS name</div><div className="mt-0.5 font-mono text-xs text-neutral-600">&lt;label&gt;.&lt;your-name&gt;.eth</div><div className="mt-1 text-xs text-neutral-500">Owner verified on ENSv2. Sign 2 txs</div>
            </button>
          </div>
          {mode === "creator" && (
            <>
              <input className={`${inputCls} mt-2`} placeholder="nakamine.eth (a name you own on Sepolia ENSv2)" value={ownName} onChange={(e) => setOwnName(e.target.value.toLowerCase())} />
              <EnsNameCheck name={ownName} onStatus={onOwnStatus} />
              <div className="mt-2 rounded-md border border-dashed border-neutral-300 p-3 text-xs text-neutral-600">
                <div className="font-medium text-neutral-900">What you will sign with your Wallet when publishing (makes the Agent a Namespace)</div>
                <ol className="mt-1 list-decimal space-y-0.5 pl-4">
                  <li>Issue the subname and its profile (text records)</li>
                  <li>Create the Agent&apos;s own Subregistry (root = you) and set it on the name</li>
                  <li>Allow the platform&apos;s Project key to only &quot;Issue project subnames&quot; (EAC ROLE_REGISTRAR)</li>
                  <li>Issue the reputation subname owned by the Reputation key (only this key can write Ratings)</li>
                  <li><label className="inline-flex items-center gap-1"><input type="checkbox" checked={subagents} onChange={(e) => setSubagents(e.target.checked)} />Also Issue subnames for the specialist AI agents ({subs.map((x) => x.role || "?").join(" / ") || "none"}) (+{subs.length ? subs.length + 1 : 0} tx)</label></li>
                </ol>
                <div className="mt-1 text-neutral-500">Up to {6 + (subagents && subs.length ? subs.length + 1 : 0)} txs in total. You remain the Owner of the name and Records; the platform only receives limited permissions.</div>
              </div>
            </>
          )}
        </Field>
        <Field label="ENS label" hint={`Publishes to: ${ens} (lowercase letters, digits, hyphens)`}>
          <input className={inputCls} placeholder="web-pm" value={f.label} onChange={(e) => set("label", e.target.value.toLowerCase())} />
        </Field>
        <Field label="Description"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="Category">
            <select className={inputCls} value={f.category} onChange={(e) => set("category", e.target.value)}>
              {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="Fee (%)">
            <input className={inputCls} type="number" min={0} max={50} step={0.5} value={f.fee_bps / 100} onChange={(e) => set("fee_bps", Math.round(Number(e.target.value) * 100))} />
          </Field>
        </div>
        <Field label="Approach & rules" hint="Becomes the PM Agent's system prompt: how to split Tasks, what work to hand to humans, Deliverable format, etc.">
          <textarea className={inputCls} rows={5} placeholder={"1. Split the Case into 4-6 Tasks\n2. Make on-site checks and physical reviews Human Tasks\n3. Write Deliverables in Markdown"} value={f.rules} onChange={(e) => set("rules", e.target.value)} />
        </Field>
        <SubagentsEditor value={subs} onChange={setSubs} agentEns={ens} />
        <PolicyEditor value={policy} onChange={(v) => { setPolicy(v); setPolicyTouched(true); }} errors={pErrs} />
        <Field label="Payout address" hint="Defaults to your Wallet if empty. Also registered as the ENS addr Record">
          <input className={inputCls} placeholder={me.wallet_address} value={f.payout_address} onChange={(e) => set("payout_address", e.target.value)} />
        </Field>
        {Object.keys(pErrs).length > 0 ? <p className="text-sm font-medium text-neutral-900">Please check the Steps / human usage inputs (items marked ⚠)</p> : <ErrorBox error={err} />}
        {failedPublish && <p className="text-xs text-neutral-700">The Agent has been created. Transactions already sent remain valid, so continue from &quot;Sign remaining txs&quot; in <Link href="/agents/mine" className="underline">My Agents</Link> (you only re-sign the steps that are incomplete).</p>}
        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={busy || !!subagentsValid(subs) || !f.label} onClick={() => submit(false)}>Save draft</Button>
          <Button disabled={busy || !!subagentsValid(subs) || !f.label || (mode === "creator" && (!/^[a-z0-9-]+\.eth$/.test(ownName) || !ownOk.ok))} onClick={() => submit(true)}>{step ?? (busy ? "Processing…" : "Publish to ENS")}</Button>
        </div>
      </Card>
    </div>
  );
}
