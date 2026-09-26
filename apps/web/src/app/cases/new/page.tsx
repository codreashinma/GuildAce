"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { api, type Agent, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WorldVerifyButton } from "@/components/world-verify";
import { Button, Card, ErrorBox, Field, inputCls, PageTitle, selectCls } from "@/components/ui";

function Steps({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex flex-wrap gap-2 text-xs">
      {["Write your request", "Choose approvers", "Verify with World and submit"].map((s, i) => (
        <li key={s} className={`whitespace-nowrap rounded-sm border px-3 py-1 tabular-nums ${step === i + 1 ? "border-neutral-900 bg-neutral-900 text-white" : step > i + 1 ? "border-neutral-900 text-neutral-900" : "border-neutral-200 text-neutral-400"}`}>{i + 1}. {s}</li>
      ))}
    </ol>
  );
}

/** UC-001 依頼登録: 自然言語 1 つ（NFR-008）→ 承認者の設定（openCase で固定）→ World で本人確認（FR-002）して依頼開始（FR-001） */
function Form() {
  const router = useRouter();
  const sp = useSearchParams();
  const { me } = useAuth();
  const { data: agents } = useQuery({ queryKey: ["agents", "all"], queryFn: () => api<Agent[]>("/agents") });
  const [prompt, setPrompt] = useState("I want to build a restaurant booking web service in 3 days. Budget is 12 USDC. I also want photos of the actual restaurant.");
  const [f, setF] = useState({ agent_id: sp.get("agent") ?? "", title: "", description: "", budget_usdc: 12, deadline: "" });
  const [approvers, setApprovers] = useState<string[]>([]);
  const [threshold, setThreshold] = useState(1);
  const [extra, setExtra] = useState("");
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [err, setErr] = useState<unknown>(null);
  const [signal, setSignal] = useState(() => crypto.randomUUID());
  const agentId = f.agent_id || agents?.[0]?.id || "";
  const agent = agents?.find((a) => a.id === agentId);

  const parsed = useMemo(() => {
    const budget = Number((prompt.match(/([\d,]+)\s*USDC/) ?? [])[1]?.replace(/,/g, "")) || f.budget_usdc;
    const daysM = prompt.match(/(\d+)\s*(?:日|days?\b)/i);
    const title = (prompt.split(/[。\n]|\.\s/)[0] || "").replace(/を?作りたい.*$/, "").replace(/^I(?: want|'d like) to (?:build|create|make)\s+/i, "").replace(/\s+(?:in|within)\s+\d+\s*days?\b.*$/i, "").trim() || "Request";
    return { budget, days: daysM ? Number(daysM[1]) : null, title };
  }, [prompt, f.budget_usdc]);

  const toStep2 = () => {
    const deadline = parsed.days ? new Date(Date.now() + parsed.days * 86400000).toISOString().slice(0, 10) : f.deadline;
    setF((s) => ({ ...s, title: parsed.title, description: prompt, budget_usdc: parsed.budget, deadline }));
    if (me && approvers.length === 0) setApprovers([me.wallet_address]);
    setStep(2);
  };

  const submit = async (idkit: unknown) => {
    setErr(null);
    try {
      const c = await api<Case>("/cases", { method: "POST", json: { ...f, agent_id: agentId, deadline: f.deadline || null, approvers, threshold, idkit_response: idkit, world_signal: signal } });
      router.push(`/cases/${c.id}`);
    } catch (e) {
      setErr(e);
      setSignal(crypto.randomUUID());  // 失敗した proof は使い回さない。次は新しい signal と rp_context で確認する
      throw e;
    }
  };

  if (!me) return <p className="text-sm text-neutral-500">Please sign in.</p>;
  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="Start a request" sub="Just describe what you want built, the deadline, and the budget in one sentence. The PM Agent breaks it into tasks, finds candidates via ENS, and assembles a team" />
      <Steps step={step} />
      {step === 1 && (
        <Card className="space-y-4">
          <Field label="Request (natural language)" hint='e.g. "Build a web service in 3 days with a 12 USDC budget!"'>
            <textarea className={`${inputCls} text-base`} rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          <div className="grid gap-3 rounded-md border border-neutral-200 p-3 text-sm sm:grid-cols-3">
            <div><div className="text-xs text-neutral-500">Detected title</div><div className="font-medium">{parsed.title}</div></div>
            <div><div className="text-xs text-neutral-500">Budget</div><div className="whitespace-nowrap font-medium tabular-nums">{parsed.budget.toLocaleString()} USDC</div></div>
            <div><div className="text-xs text-neutral-500">Deadline</div><div className="font-medium">{parsed.days ? `In ${parsed.days} ${parsed.days === 1 ? "day" : "days"}` : "Not specified"}</div></div>
          </div>
          <Field label="PM Agent to use">
            <select className={inputCls} value={agentId} onChange={(e) => setF({ ...f, agent_id: e.target.value })}>
              {agents?.map((a) => <option key={a.id} value={a.id}>{a.name} — {a.ens_name} (Fee {a.fee_bps / 100}%)</option>)}
            </select>
          </Field>
          <div className="flex justify-end"><Button disabled={!prompt || !agentId} onClick={toStep2}>Next</Button></div>
        </Card>
      )}
      {step === 2 && (
        <Card className="space-y-4">
          <h2 className="font-semibold">Choose approvers</h2>
          <p className="text-sm text-neutral-600">These are the wallets that can approve deliverables for acceptance, and the number of approvals required for payment. They are fixed by Escrow&apos;s openCase, and the contract pays automatically once the required number is reached. Only the permissions registered here can approve, not names.</p>
          <ul className="space-y-1 text-sm">
            {approvers.map((a, i) => (
              <li key={a} className="flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-xs">
                <span className="shrink-0 whitespace-nowrap rounded-sm border border-neutral-900 px-1.5 text-[10px]">{i === 0 ? "Engineering (acceptance)" : i === 1 ? "Finance (payment)" : `Approver ${i + 1}`}</span><span className="truncate font-mono">{a}</span>
                {approvers.length > 1 && <button className="ml-auto whitespace-nowrap underline underline-offset-2" onClick={() => setApprovers(approvers.filter((x) => x !== a))}>Delete</button>}
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input className={inputCls} placeholder="Approver wallet 0x… (e.g. Finance)" value={extra} onChange={(e) => setExtra(e.target.value)} />
            <Button variant="secondary" disabled={!/^0x[0-9a-fA-F]{40}$/.test(extra)} onClick={() => { setApprovers([...approvers, extra.toLowerCase()]); setExtra(""); }}>Add</Button>
          </div>
          <Field label="Required approvals">
            <select className={selectCls} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
              {approvers.map((_, i) => <option key={i} value={i + 1}>{i + 1} / {approvers.length}</option>)}
            </select>
          </Field>
          <div className="flex justify-between"><Button variant="secondary" onClick={() => setStep(1)}>Back</Button><Button disabled={approvers.length === 0} onClick={() => setStep(3)}>Next</Button></div>
        </Card>
      )}
      {step === 3 && (
        <Card className="space-y-4">
          <h2 className="font-semibold">Review and start the request</h2>
          <Field label="Title"><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="Request details"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Budget (USDC)"><input className={inputCls} type="number" min={1} value={f.budget_usdc} onChange={(e) => setF({ ...f, budget_usdc: Number(e.target.value) })} /></Field>
            <Field label="Deadline"><input className={inputCls} type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          </div>
          <div className="rounded-md border border-neutral-200 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-2"><span className="whitespace-nowrap">PM Agent: <b>{agent?.name}</b></span><span className="font-mono text-xs">{agent?.ens_name}</span><span className="whitespace-nowrap tabular-nums">Fee {agent ? agent.fee_bps / 100 : "-"}%</span></div>
            <div className="whitespace-nowrap tabular-nums">{approvers.length} {approvers.length === 1 ? "approver" : "approvers"} / {threshold} required</div>
            <div className="mt-1 text-xs text-neutral-600">Starting a request is a &quot;significant action&quot;, so World ID verifies that you are a real human (FR-002). World proves only personhood, not company affiliation or contracting authority.</div>
          </div>
          <ErrorBox error={err} />
          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setStep(2)}>Back</Button>
            <WorldVerifyButton action="request" signal={signal} label="Verify with World and start request" onVerified={submit} />
          </div>
        </Card>
      )}
    </div>
  );
}

export default function NewCase() {
  return <Suspense><Form /></Suspense>;
}
