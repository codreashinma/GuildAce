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
      {["依頼を書く", "承認者を決める", "World で本人確認して依頼"].map((s, i) => (
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
  const [prompt, setPrompt] = useState("レストラン予約の Web サービスを 3 日で作りたい。予算は 12 USDC。実店舗の写真も入れたい。");
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
    const daysM = prompt.match(/(\d+)\s*日/);
    const title = (prompt.split(/[。\n]/)[0] || "").replace(/を?作りたい.*$/, "").trim() || "依頼";
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
      const c = await api<Case>("/cases", { method: "POST", json: { ...f, agent_id: agentId, deadline: f.deadline || null, approvers, threshold, idkit_response: idkit } });
      router.push(`/cases/${c.id}`);
    } catch (e) {
      setErr(e);
      setSignal(crypto.randomUUID());  // 失敗した proof は使い回さない。次は新しい signal と rp_context で確認する
      throw e;
    }
  };

  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="依頼を始める" sub="作りたいこと・納期・予算を 1 つの文章で書くだけ。PM Agent がタスクに分解し、ENS から候補を探してチームを編成します" />
      <Steps step={step} />
      {step === 1 && (
        <Card className="space-y-4">
          <Field label="依頼文（自然言語）" hint="例: 「Web サービスを 3 日で作って、予算 12 USDC で！」">
            <textarea className={`${inputCls} text-base`} rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          <div className="grid gap-3 rounded-md border border-neutral-200 p-3 text-sm sm:grid-cols-3">
            <div><div className="text-xs text-neutral-500">読み取った件名</div><div className="font-medium">{parsed.title}</div></div>
            <div><div className="text-xs text-neutral-500">予算</div><div className="whitespace-nowrap font-medium tabular-nums">{parsed.budget.toLocaleString()} USDC</div></div>
            <div><div className="text-xs text-neutral-500">納期</div><div className="font-medium">{parsed.days ? `${parsed.days} 日後` : "未指定"}</div></div>
          </div>
          <Field label="利用する PM Agent">
            <select className={inputCls} value={agentId} onChange={(e) => setF({ ...f, agent_id: e.target.value })}>
              {agents?.map((a) => <option key={a.id} value={a.id}>{a.name} — {a.ens_name} (Fee {a.fee_bps / 100}%)</option>)}
            </select>
          </Field>
          <div className="flex justify-end"><Button disabled={!prompt || !agentId} onClick={toStep2}>次へ</Button></div>
        </Card>
      )}
      {step === 2 && (
        <Card className="space-y-4">
          <h2 className="font-semibold">承認者を決める</h2>
          <p className="text-sm text-neutral-600">成果物の検収を承認できるウォレットと、支払いに必要な承認数です。Escrow の openCase で固定され、必要数がそろった時点でコントラクトが自動で支払います。名前ではなく、ここで登録した権限だけが承認できます。</p>
          <ul className="space-y-1 text-sm">
            {approvers.map((a, i) => (
              <li key={a} className="flex items-center gap-2 rounded-md border border-neutral-200 px-3 py-2 text-xs">
                <span className="shrink-0 whitespace-nowrap rounded-sm border border-neutral-900 px-1.5 text-[10px]">{i === 0 ? "開発部（検収）" : i === 1 ? "経理部（支払）" : `承認者 ${i + 1}`}</span><span className="truncate font-mono">{a}</span>
                {approvers.length > 1 && <button className="ml-auto whitespace-nowrap underline underline-offset-2" onClick={() => setApprovers(approvers.filter((x) => x !== a))}>削除</button>}
              </li>
            ))}
          </ul>
          <div className="flex gap-2">
            <input className={inputCls} placeholder="承認者のウォレット 0x…（例: 経理部）" value={extra} onChange={(e) => setExtra(e.target.value)} />
            <Button variant="secondary" disabled={!/^0x[0-9a-fA-F]{40}$/.test(extra)} onClick={() => { setApprovers([...approvers, extra.toLowerCase()]); setExtra(""); }}>追加</Button>
          </div>
          <Field label="必要承認数">
            <select className={selectCls} value={threshold} onChange={(e) => setThreshold(Number(e.target.value))}>
              {approvers.map((_, i) => <option key={i} value={i + 1}>{i + 1} / {approvers.length}</option>)}
            </select>
          </Field>
          <div className="flex justify-between"><Button variant="secondary" onClick={() => setStep(1)}>戻る</Button><Button disabled={approvers.length === 0} onClick={() => setStep(3)}>次へ</Button></div>
        </Card>
      )}
      {step === 3 && (
        <Card className="space-y-4">
          <h2 className="font-semibold">内容を確認して依頼を開始</h2>
          <Field label="件名"><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="依頼内容"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="予算（USDC）"><input className={inputCls} type="number" min={1} value={f.budget_usdc} onChange={(e) => setF({ ...f, budget_usdc: Number(e.target.value) })} /></Field>
            <Field label="納期"><input className={inputCls} type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          </div>
          <div className="rounded-md border border-neutral-200 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-2"><span className="whitespace-nowrap">PM Agent: <b>{agent?.name}</b></span><span className="font-mono text-xs">{agent?.ens_name}</span><span className="whitespace-nowrap tabular-nums">手数料 {agent ? agent.fee_bps / 100 : "-"}%</span></div>
            <div className="whitespace-nowrap tabular-nums">承認者 {approvers.length} 名 / 必要 {threshold}</div>
            <div className="mt-1 text-xs text-neutral-600">依頼の開始は「重要な行為」なので、World ID で実在する人間であることを確認します（FR-002）。World は人間性だけを証明し、会社への所属や契約権限は証明しません。</div>
          </div>
          <ErrorBox error={err} />
          <div className="flex justify-between">
            <Button variant="secondary" onClick={() => setStep(2)}>戻る</Button>
            <WorldVerifyButton action="request" signal={signal} label="World で人間確認して依頼を開始" onVerified={submit} />
          </div>
        </Card>
      )}
    </div>
  );
}

export default function NewCase() {
  return <Suspense><Form /></Suspense>;
}
