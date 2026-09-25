"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { api, type Agent, type Case } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Field, inputCls, PageTitle } from "@/components/ui";

function Form() {
  const router = useRouter();
  const sp = useSearchParams();
  const { me } = useAuth();
  const { data: agents } = useQuery({ queryKey: ["agents", "all"], queryFn: () => api<Agent[]>("/agents") });
  const [f, setF] = useState({ agent_id: sp.get("agent") ?? "", title: "Web サービスを作りたい", description: "", budget_usdc: 300, deadline: "" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const agentId = f.agent_id || agents?.[0]?.id || "";

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
      <PageTitle title="案件を作成" sub="PM Agent がタスクに分解し、AI と人間のチームを編成します。承認時に予算を Escrow に預けます" />
      <Card className="space-y-4">
        <Field label="利用する PM Agent">
          <select className={inputCls} value={agentId} onChange={(e) => setF({ ...f, agent_id: e.target.value })}>
            {agents?.map((a) => <option key={a.id} value={a.id}>{a.name} — {a.ens_name} (Fee {a.fee_bps / 100}%)</option>)}
          </select>
        </Field>
        <Field label="タイトル"><input className={inputCls} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} /></Field>
        <Field label="説明"><textarea className={inputCls} rows={4} placeholder="例: レストラン予約の Web サービスを 3 日で。実店舗の写真も欲しい" value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="予算（USDC）"><input className={inputCls} type="number" min={1} value={f.budget_usdc} onChange={(e) => setF({ ...f, budget_usdc: Number(e.target.value) })} /></Field>
          <Field label="納期"><input className={inputCls} type="date" value={f.deadline} onChange={(e) => setF({ ...f, deadline: e.target.value })} /></Field>
        </div>
        <ErrorBox error={err} />
        <div className="flex justify-end"><Button disabled={busy || !agentId} onClick={submit}>{busy ? "作成中…" : "案件を作成"}</Button></div>
      </Card>
    </div>
  );
}

export default function NewCase() {
  return <Suspense><Form /></Suspense>;
}
