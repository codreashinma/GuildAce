"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, short, usdc, type HumanTask } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WorldVerifyButton } from "@/components/world-verify";
import { Amount, BackLink, Badge, Button, Card, ErrorBox, HumanBadge, inputCls, KindTag, Mono } from "@/components/ui";

export default function TaskPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data: t } = useQuery({ queryKey: ["human-task", id], queryFn: () => api<HumanTask>(`/human-tasks/${id}`), refetchInterval: 4000 });
  const [submission, setSubmission] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["human-task", id] }); qc.invalidateQueries({ queryKey: ["human-tasks"] }); };
  if (!t) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  const isWorker = me && t.worker?.id === me.id;

  const call = async (path: string, json?: unknown) => {
    setBusy(true);
    setErr(null);
    try { await api(path, { method: "POST", json: json ?? {} }); refresh(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <BackLink href="/tasks">Human Task 一覧</BackLink>
      <Card>
        <div className="flex items-start justify-between gap-3"><h1 className="flex min-w-0 items-center gap-2 text-xl font-bold"><KindTag kind="human" /><span>{t.title}</span></h1><Badge status={t.status} className="mt-1" /></div>
        <p className="mt-2 whitespace-pre-wrap text-sm text-neutral-700">{t.description}</p>
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm"><span className="whitespace-nowrap">報酬 <Amount value={usdc(t.reward)} className="font-semibold" /></span><span className="text-xs text-neutral-500">検収承認後に Escrow から自動支払い</span><Link href={`/cases/${t.case_id}`} className="whitespace-nowrap text-neutral-900 underline underline-offset-2">元の案件</Link></div>
        {t.worker && <div className="mt-2 flex flex-wrap items-center gap-2 text-sm"><span className="whitespace-nowrap">受注者 <Mono>{short(t.worker.wallet_address)}</Mono></span><HumanBadge /></div>}
        {t.assignee && (
          <div className="mt-3 rounded-md border border-neutral-900 p-3 text-sm">
            <div className="flex flex-wrap items-center gap-x-2"><span className="whitespace-nowrap">PM Agent の指名: <b>{t.assignee.name}</b>（{t.assignee.role}）</span><Mono className="text-neutral-900">{t.assignee.ens_name}</Mono></div>
            <div className="mt-1 flex flex-wrap gap-x-3 text-xs text-neutral-600"><span>スキル: {t.assignee.skills}</span><span className="whitespace-nowrap">拠点: {t.assignee.location}</span></div>
            {t.assignment_reason && <div className="mt-1 text-xs text-neutral-900">理由: {t.assignment_reason}</div>}
          </div>
        )}
        {t.status === "open" && t.assignment_reason && <p className="mt-2 text-xs text-neutral-500">{t.assignment_reason}</p>}
      </Card>

      {t.status === "assigned" && me && t.assignee?.wallet_address === me.wallet_address && (
        <Card>
          <p className="mb-3 text-sm">あなたが指名されています。World で人間であることを確認して受諾するか、辞退して次の候補に回してください。</p>
          <div className="flex flex-wrap gap-2">
            <WorldVerifyButton action="human-task" signal={t.id} label="World で人間確認して受諾する" onVerified={async (p) => { await api(`/human-tasks/${t.id}/accept`, { method: "POST", json: { idkit_response: p } }); refresh(); }} />
            <Button variant="secondary" disabled={busy} onClick={() => call(`/human-tasks/${t.id}/decline`)}>辞退する</Button>
          </div>
          <div className="mt-2"><ErrorBox error={err} /></div>
        </Card>
      )}
      {t.status === "assigned" && me && t.assignee?.wallet_address !== me.wallet_address && <Card><p className="text-sm text-neutral-500">このタスクは別の人員に指名中です。辞退された場合に再指名・公開募集されます。</p></Card>}
      {t.status === "open" && me && (
        <Card>
          <p className="mb-3 text-sm">このタスクは World で人間であることを確認した人だけが受注できます。</p>
          <WorldVerifyButton action="human-task" signal={t.id} label="World で人間確認して受注する" onVerified={async (p) => { await api(`/human-tasks/${t.id}/accept`, { method: "POST", json: { idkit_response: p } }); refresh(); }} />
        </Card>
      )}
      {t.status === "open" && !me && <Card><p className="text-sm text-neutral-500">受注するには Sign in してください。</p></Card>}

      {t.status === "accepted" && isWorker && (
        <Card className="space-y-2">
          <h2 className="font-semibold">成果物を提出</h2>
          <textarea className={inputCls} rows={4} placeholder="写真の URL、確認結果、感想など" value={submission} onChange={(e) => setSubmission(e.target.value)} />
          <div className="flex gap-2">
            <Button onClick={() => call(`/human-tasks/${t.id}/submit`, { submission })} disabled={busy || !submission}>提出する</Button>
            <Button variant="secondary" onClick={() => call(`/human-tasks/${t.id}/cancel`)} disabled={busy}>受注をキャンセル</Button>
          </div>
          <ErrorBox error={err} />
        </Card>
      )}

      {t.submission && (
        <Card>
          <h2 className="font-semibold">提出内容</h2>
          <p className="mt-1 whitespace-pre-wrap text-sm">{t.submission}</p>
          {t.ai_check && <p className="mt-3 rounded-md bg-neutral-100 p-3 text-sm"><span className="mr-2 inline-flex rounded-sm border border-neutral-900 px-1 text-[10px] font-semibold leading-4">AI</span>PM Agent の確認: {t.ai_check}</p>}
        </Card>
      )}
    </div>
  );
}
