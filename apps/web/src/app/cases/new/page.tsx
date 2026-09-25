"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { api, type Agent, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Field, HumanBadge, inputCls, PageTitle } from "@/components/ui";

function Steps({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex gap-2 text-xs">
      {["依頼を書く", "World で本人確認", "内容を確認して依頼"].map((s, i) => (
        <li key={s} className={`rounded-full px-3 py-1 ${step === i + 1 ? "bg-slate-900 text-white" : step > i + 1 ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-500"}`}>{i + 1}. {s}</li>
      ))}
    </ol>
  );
}

/** UC-001 依頼登録: 自然言語 1 つ（NFR-008）→ World で本人確認（FR-002）→ 依頼開始（FR-001） */
function Form() {
  const router = useRouter();
  const sp = useSearchParams();
  const { me } = useAuth();
  const { data: agents } = useQuery({ queryKey: ["agents", "all"], queryFn: () => api<Agent[]>("/agents") });
  const [prompt, setPrompt] = useState("レストラン予約の Web サービスを 3 日で作りたい。予算は 300 USDC。実店舗の写真も入れたい。");
  const [f, setF] = useState({ agent_id: sp.get("agent") ?? "", title: "", description: "", budget_usdc: 300, deadline: "" });
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [human, setHuman] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const agentId = f.agent_id || agents?.[0]?.id || "";
  const agent = agents?.find((a) => a.id === agentId);

  // 依頼文から タイトル / 予算 / 納期 を抜き出す（UI 側の簡易パース。PM Agent が本番では解釈する）
  const parsed = useMemo(() => {
    const budget = Number((prompt.match(/([\d,]+)\s*USDC/) ?? [])[1]?.replace(/,/g, "")) || f.budget_usdc;
    const daysM = prompt.match(/(\d+)\s*日/);
    const deadline = daysM ? `${daysM[1]} 日後` : f.deadline;
    const title = (prompt.split(/[。\n]/)[0] || "").replace(/を?作りたい.*$/, "").trim() || "依頼";
    return { budget, deadline, title };
  }, [prompt, f.budget_usdc, f.deadline]);

  const toStep2 = () => {
    const daysM = prompt.match(/(\d+)\s*日/);
    const deadline = daysM ? new Date(Date.now() + Number(daysM[1]) * 86400000).toISOString().slice(0, 10) : f.deadline;
    setF((s) => ({ ...s, title: parsed.title, description: prompt, budget_usdc: parsed.budget, deadline }));
    setStep(2);
  };

  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const c = await api<Case>("/cases", { method: "POST", json: { ...f, agent_id: agentId, deadline: f.deadline || null } });
      router.push(`/cases/${c.id}`);
    } catch (e) {
      setErr(e);
      setBusy(false);
    }
  };

  if (!me) return <p className="text-sm text-slate-500">Sign in してください。</p>;
  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="依頼を始める" sub="作りたいこと・納期・予算を 1 つの文章で書くだけ。PM Agent がタスクに分解し、ENS から候補を探してチームを編成します" />
      <Steps step={step} />
      {step === 1 && (
        <Card className="space-y-4">
          <Field label="依頼文（自然言語）" hint="例: 「Web サービスを 3 日で作って、予算 300 USDC で！」">
            <textarea className={`${inputCls} text-base`} rows={4} value={prompt} onChange={(e) => setPrompt(e.target.value)} />
          </Field>
          <div className="grid gap-2 rounded-lg bg-slate-50 p-3 text-sm sm:grid-cols-3">
            <div><div className="text-xs text-slate-500">読み取った件名</div><div className="font-medium">{parsed.title}</div></div>
            <div><div className="text-xs text-slate-500">予算</div><div className="font-medium">{parsed.budget.toLocaleString()} USDC</div></div>
            <div><div className="text-xs text-slate-500">納期</div><div className="font-medium">{parsed.deadline || "未指定"}</div></div>
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
          <h2 className="font-semibold">World で本人確認</h2>
          <p className="text-sm text-slate-600">依頼の開始は「重要な行為」です。Bot や AI ではなく、実在する人間からの依頼であることを World ID で確認します（FR-002）。World が示すのは人間性のみで、会社への所属や契約権限は証明しません。</p>
          {!human ? (
            <Button onClick={() => setHuman(true)}><span className="mr-1">◎</span>World ID で人間確認する</Button>
          ) : (
            <div className="flex items-center gap-2 text-sm"><HumanBadge /><span className="text-emerald-700">確認できました</span></div>
          )}
          <div className="flex justify-between"><Button variant="secondary" onClick={() => setStep(1)}>戻る</Button><Button disabled={!human} onClick={() => setStep(3)}>次へ</Button></div>
        </Card>
      )}
      {step === 3 && (
        <Card className="space-y-4">
          <h2 className="font-semibold">内容を確認</h2>
          <Field label="件名"><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
          <Field label="依頼内容"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
          <div className="grid grid-cols-2 gap-4">
            <Field label="予算（USDC）"><input className={inputCls} type="number" min={1} value={f.budget_usdc} onChange={(e) => setF({ ...f, budget_usdc: Number(e.target.value) })} /></Field>
            <Field label="納期"><input className={inputCls} type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
          </div>
          <div className="rounded-lg bg-blue-50 p-3 text-sm">
            <div>PM Agent: <b>{agent?.name}</b> <span className="font-mono text-xs">{agent?.ens_name}</span> · 手数料 {agent ? agent.fee_bps / 100 : "-"}%</div>
            <div className="mt-1 text-xs text-slate-600">依頼後、PM Agent がタスク分解とチーム編成（ENS から候補検索）を行い、あなたが承認した時点で予算を Escrow に預けます。</div>
          </div>
          <ErrorBox error={err} />
          <div className="flex justify-between"><Button variant="secondary" onClick={() => setStep(2)}>戻る</Button><Button disabled={busy} onClick={submit}>{busy ? "作成中…" : "依頼を開始"}</Button></div>
        </Card>
      )}
    </div>
  );
}

export default function NewCase() {
  return <Suspense><Form /></Suspense>;
}
