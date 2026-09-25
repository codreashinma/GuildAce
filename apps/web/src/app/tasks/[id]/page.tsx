"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { api, short, usdc, type HumanTask } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WorldVerifyButton } from "@/components/world-verify";
import { BackLink, Badge, Button, Card, ErrorBox, HumanBadge, inputCls } from "@/components/ui";

export default function TaskPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me } = useAuth();
  const qc = useQueryClient();
  const { data: t } = useQuery({ queryKey: ["human-task", id], queryFn: () => api<HumanTask>(`/human-tasks/${id}`), refetchInterval: 4000 });
  const [submission, setSubmission] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const refresh = () => { qc.invalidateQueries({ queryKey: ["human-task", id] }); qc.invalidateQueries({ queryKey: ["human-tasks"] }); };
  if (!t) return <p className="text-sm text-slate-500">読み込み中…</p>;
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
        <div className="flex items-center justify-between gap-2"><h1 className="text-xl font-bold">🧑 {t.title}</h1><Badge status={t.status} /></div>
        <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{t.description}</p>
        <div className="mt-3 flex flex-wrap gap-4 text-sm"><span>報酬 <b>{usdc(t.reward)} USDC</b>（案件の検収承認後に Escrow から支払い）</span><Link href={`/cases/${t.case_id}`} className="text-blue-700 underline">元の案件</Link></div>
        {t.worker && <div className="mt-2 flex items-center gap-2 text-sm">受注者 {short(t.worker.wallet_address)} <HumanBadge /></div>}
      </Card>

      {t.status === "open" && me && (
        <Card>
          <p className="mb-3 text-sm">このタスクは World で人間であることを確認した人だけが受注できます。</p>
          <WorldVerifyButton action="human-task" signal={t.id} label="World で人間確認して受注する" onVerified={async (p) => { await api(`/human-tasks/${t.id}/accept`, { method: "POST", json: { idkit_response: p } }); refresh(); }} />
        </Card>
      )}
      {t.status === "open" && !me && <Card><p className="text-sm text-slate-500">受注するには Sign in してください。</p></Card>}

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
          {t.ai_check && <p className="mt-3 rounded-lg bg-blue-50 p-3 text-sm">🤖 PM Agent の確認: {t.ai_check}</p>}
        </Card>
      )}
    </div>
  );
}
