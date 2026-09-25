"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";
import { api, short, STATUS_LABEL, usdc, type CaseDetail, type Review, type Task } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { erc20Abi, escrowAbi } from "@/lib/contracts";
import { Markdown } from "@/components/markdown";
import { WorldVerifyButton } from "@/components/world-verify";
import { BackLink, Badge, Button, Card, ErrorBox, HumanBadge, inputCls, Stars, TxLink } from "@/components/ui";

const STEPS = ["planning", "awaiting_approval", "in_progress", "delivered", "completed"];

export default function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me, config } = useAuth();
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["case", id], queryFn: () => api<CaseDetail>(`/cases/${id}`), refetchInterval: 3000 });
  const { data: reviews } = useQuery({ queryKey: ["case-reviews", id], queryFn: () => api<Review[]>(`/reviews/case/${id}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["case", id] }); qc.invalidateQueries({ queryKey: ["case-reviews", id] }); };
  if (!c) return <p className="text-sm text-slate-500">読み込み中…</p>;
  const isClient = me?.id === c.client.id;
  const stepIdx = Math.max(STEPS.indexOf(c.status), c.status === "disputed" || c.status === "resolved" ? 3 : 0);
  const taskCost = c.tasks.reduce((s, t) => s + Number(t.estimated_cost), 0);

  return (
    <div className="space-y-6">
      <BackLink href="/cases">案件一覧</BackLink>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-bold">{c.title}</h1><Badge status={c.status} /></div>
            <p className="mt-1 text-sm text-slate-500">PM Agent: <Link href={`/agents/${c.agent.id}`} className="text-blue-700 hover:underline">{c.agent.name}</Link> <span className="font-mono">{c.agent.ens_name}</span> · 発注者 {short(c.client.wallet_address)}</p>
            {c.description && <p className="mt-2 whitespace-pre-wrap text-sm text-slate-700">{c.description}</p>}
          </div>
          <div className="text-right"><div className="text-2xl font-bold">{usdc(c.budget)} <span className="text-sm font-normal">USDC</span></div><div className="text-xs text-slate-500">Escrow: {c.escrow_case_id.slice(0, 10)}…</div></div>
        </div>
        <ol className="mt-5 flex flex-wrap gap-2 text-xs">
          {STEPS.map((s, i) => (
            <li key={s} className={`rounded-full px-3 py-1 ${i < stepIdx ? "bg-emerald-100 text-emerald-800" : i === stepIdx ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-500"}`}>{i + 1}. {STATUS_LABEL[s]}</li>
          ))}
        </ol>
        <div className="mt-3 flex flex-wrap gap-4"><TxLink hash={c.deposit_tx_hash} label="入金" /><TxLink hash={c.release_tx_hash} label="支払い" /></div>
        {c.error && <ErrorBox error={c.error} />}
      </Card>

      {c.status === "planning" && <Card><p className="animate-pulse text-sm">🤖 {c.agent.name} がタスクを分解し、チームを編成しています…</p></Card>}
      {c.status === "planning_failed" && isClient && <Card><ErrorBox error={c.error} /><Button className="mt-3" onClick={() => api(`/cases/${id}/replan`, { method: "POST" }).then(refresh)}>再計画する</Button></Card>}

      {c.plan_json && (
        <Card>
          <h2 className="font-semibold">計画とチーム編成 <span className="text-xs font-normal text-slate-500">PM Agent が生成</span></h2>
          <p className="mt-1 text-sm text-slate-700">{c.plan_json.summary}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {c.plan_json.team?.map((m) => <span key={m.name} className={`rounded-full px-3 py-1 text-xs ${m.kind === "human" ? "bg-amber-100 text-amber-900" : "bg-blue-100 text-blue-900"}`}>{m.kind === "human" ? "🧑" : "🤖"} {m.name}</span>)}
          </div>
          <p className="mt-3 text-xs text-slate-500">タスク合計 {usdc(taskCost)} USDC + PM 手数料 {c.agent.fee_bps / 100}% ≤ 予算 {usdc(c.budget)} USDC</p>
          {c.status === "awaiting_approval" && isClient && <DepositPanel c={c} mock={!!config?.mock.chain} onDone={refresh} />}
        </Card>
      )}

      {c.tasks.length > 0 && <TaskBoard tasks={c.tasks} />}

      {c.status === "delivered" && isClient && <ReleasePanel c={c} mock={!!config?.mock.chain} onDone={refresh} />}
      {c.status === "disputed" && <Card><p className="text-sm">⚖️ 紛争中です。資金は Escrow に保留されています。 <Link className="text-blue-700 underline" href={`/jury/${c.dispute_id}`}>Jury 画面へ</Link></p></Card>}
      {c.status === "resolved" && <Card><p className="text-sm">⚖️ Human Jury の多数決で解決しました。 <Link className="text-blue-700 underline" href={`/jury/${c.dispute_id}`}>結果を見る</Link></p></Card>}

      {(c.status === "completed" || c.status === "resolved") && me && (
        <ReviewPanel c={c} reviews={reviews ?? []} meId={me.id} onDone={refresh} />
      )}
    </div>
  );
}

function DepositPanel({ c, mock, onDone }: { c: CaseDetail; mock: boolean; onDone: () => void }) {
  const { config } = useAuth();
  const { address } = useAccount();
  const { writeContractAsync } = useWriteContract();
  const pc = usePublicClient();
  const [err, setErr] = useState<unknown>(null);
  const [step, setStep] = useState<string | null>(null);
  const amount = BigInt(c.budget);

  const run = async () => {
    setErr(null);
    try {
      let txHash: string;
      if (mock) {
        txHash = "0x" + Array.from(crypto.getRandomValues(new Uint8Array(32))).map((b) => b.toString(16).padStart(2, "0")).join("");
      } else {
        if (!config || !address || !pc) throw new Error("ウォレット未接続");
        const escrow = config.escrow_address as `0x${string}`;
        const token = config.usdc_address as `0x${string}`;
        const bal = await pc.readContract({ address: token, abi: erc20Abi, functionName: "balanceOf", args: [address] });
        if (bal < amount) {
          setStep("テスト用 USDC を mint 中…");
          const h = await writeContractAsync({ address: token, abi: erc20Abi, functionName: "mint", args: [address, amount - bal] });
          await pc.waitForTransactionReceipt({ hash: h });
        }
        const allowance = await pc.readContract({ address: token, abi: erc20Abi, functionName: "allowance", args: [address, escrow] });
        if (allowance < amount) {
          setStep("USDC の approve に署名…");
          const h = await writeContractAsync({ address: token, abi: erc20Abi, functionName: "approve", args: [escrow, amount] });
          await pc.waitForTransactionReceipt({ hash: h });
        }
        setStep("Escrow に入金（deposit）に署名…");
        const h = await writeContractAsync({ address: escrow, abi: escrowAbi, functionName: "deposit", args: [c.escrow_case_id as `0x${string}`, token, amount] });
        setStep("トランザクション確認中…");
        await pc.waitForTransactionReceipt({ hash: h });
        txHash = h;
      }
      setStep("API に入金を通知…");
      await api(`/cases/${c.id}/funded`, { method: "POST", json: { tx_hash: txHash } });
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setStep(null);
    }
  };
  return (
    <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50 p-4">
      <p className="text-sm">計画を承認すると、予算 <b>{usdc(c.budget)} USDC</b> を Escrow（スマートコントラクト）に預けて作業が始まります。支払いはあなたの検収承認まで動きません。</p>
      <div className="mt-3 flex items-center gap-3">
        <Button onClick={run} disabled={!!step}>{step ?? (mock ? "承認して入金（モック）" : "承認して入金する")}</Button>
      </div>
      <div className="mt-2"><ErrorBox error={err} /></div>
    </div>
  );
}

function ReleasePanel({ c, mock, onDone }: { c: CaseDetail; mock: boolean; onDone: () => void }) {
  const { config } = useAuth();
  const { writeContractAsync } = useWriteContract();
  const pc = usePublicClient();
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState("");
  const [showDispute, setShowDispute] = useState(false);

  const release = async () => {
    setBusy(true);
    setErr(null);
    try {
      let txHash: string;
      if (mock) {
        txHash = "0x" + Array.from(crypto.getRandomValues(new Uint8Array(32))).map((b) => b.toString(16).padStart(2, "0")).join("");
      } else {
        if (!config || !pc) throw new Error("ウォレット未接続");
        const h = await writeContractAsync({
          address: config.escrow_address as `0x${string}`, abi: escrowAbi, functionName: "release",
          args: [c.escrow_case_id as `0x${string}`, c.split.map((s) => s.address as `0x${string}`), c.split.map((s) => BigInt(s.amount))],
        });
        await pc.waitForTransactionReceipt({ hash: h });
        txHash = h;
      }
      await api(`/cases/${c.id}/released`, { method: "POST", json: { tx_hash: txHash } });
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  const dispute = async () => {
    setBusy(true);
    setErr(null);
    try {
      await api(`/cases/${c.id}/dispute`, { method: "POST", json: { reason } });
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Card className="border-violet-200 bg-violet-50">
      <h2 className="font-semibold">検収・承認</h2>
      <p className="mt-1 text-sm">すべてのタスクが完了しました。成果物を確認し、承認すると Escrow から次の配分で支払われます。</p>
      <ul className="mt-2 space-y-1 text-sm">
        {c.split.map((s) => <li key={s.address} className="flex justify-between"><span>{s.label} <span className="font-mono text-xs text-slate-500">{short(s.address)}</span></span><b>{usdc(s.amount)} USDC</b></li>)}
      </ul>
      <div className="mt-4 flex flex-wrap gap-2">
        <Button onClick={release} disabled={busy}>{busy ? "処理中…" : mock ? "承認して支払う（モック）" : "承認して支払う"}</Button>
        <Button variant="danger" onClick={() => setShowDispute((v) => !v)} disabled={busy}>差し戻す</Button>
      </div>
      {showDispute && (
        <div className="mt-3 space-y-2">
          <textarea className={inputCls} rows={3} placeholder="差し戻し理由（例: 約束した機能が足りない）" value={reason} onChange={(e) => setReason(e.target.value)} />
          <p className="text-xs text-slate-600">差し戻すと資金は保留され、AI が論点を整理したうえで World で確認された第三者（Human Jury）3 名の多数決で支払い / 返金が決まります。</p>
          <Button variant="danger" onClick={dispute} disabled={busy || !reason}>差し戻して Jury に回す</Button>
        </div>
      )}
      <div className="mt-2"><ErrorBox error={err} /></div>
    </Card>
  );
}

function TaskBoard({ tasks }: { tasks: Task[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  const cols: [string, string, Task[]][] = [
    ["todo", "ToDo", tasks.filter((t) => t.status === "todo")],
    ["in_progress", "進行中", tasks.filter((t) => t.status === "in_progress")],
    ["done", "完了", tasks.filter((t) => t.status === "done")],
  ];
  const open = tasks.find((t) => t.id === openId);
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        {cols.map(([k, label, list]) => (
          <div key={k} className="rounded-xl bg-slate-100 p-3">
            <div className="mb-2 text-xs font-semibold text-slate-600">{label} ({list.length})</div>
            <div className="space-y-2">
              {list.map((t) => (
                <button key={t.id} onClick={() => setOpenId(t.id === openId ? null : t.id)} className={`w-full rounded-lg border bg-white p-3 text-left text-sm shadow-sm hover:border-blue-400 ${openId === t.id ? "border-blue-500" : "border-slate-200"}`}>
                  <div className="flex items-center gap-2"><span>{t.type === "human" ? "🧑" : "🤖"}</span><span className="font-medium">{t.title}</span></div>
                  <div className="mt-1 flex justify-between text-xs text-slate-500"><span>{t.assignee_name}</span><span>{usdc(t.estimated_cost)} USDC</span></div>
                  {t.type === "human" && t.human_task && <div className="mt-1"><Badge status={t.human_task.status} /></div>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {open && (
        <Card className="mt-3">
          <div className="flex items-center justify-between"><h3 className="font-semibold">{open.type === "human" ? "🧑" : "🤖"} {open.title}</h3><Badge status={open.status} /></div>
          <p className="mt-1 text-sm text-slate-600">{open.description}</p>
          {open.type === "human" && open.human_task && open.human_task.status !== "done" && (
            <p className="mt-2 text-sm">Human Task として公開中 → <Link href={`/tasks/${open.human_task.id}`} className="text-blue-700 underline">タスクページ</Link></p>
          )}
          {open.deliverable && <div className="mt-3 rounded-lg bg-slate-50 p-3"><Markdown>{open.deliverable}</Markdown></div>}
        </Card>
      )}
    </div>
  );
}

function ReviewPanel({ c, reviews, meId, onDone }: { c: CaseDetail; reviews: Review[]; meId: string; onDone: () => void }) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const isClient = c.client.id === meId;
  const isWorker = c.tasks.some((t) => t.human_task?.worker?.id === meId);
  const mine = reviews.find((r) => r.reviewer.id === meId);
  const post = useMutation({
    mutationFn: (idkit: unknown) => api("/reviews", { method: "POST", json: { case_id: c.id, rating, comment, idkit_response: idkit } }),
    onSuccess: onDone, onError: setErr,
  });
  return (
    <Card>
      <h2 className="font-semibold">Human-backed Review</h2>
      <p className="mt-1 text-xs text-slate-500">案件の当事者（発注者 → PM Agent、Human Task worker → 発注者）が、World で人間確認をしてから評価します。Bot による水増しはできません。</p>
      {reviews.length > 0 && (
        <ul className="mt-3 space-y-2">
          {reviews.map((r) => <li key={r.id} className="rounded-lg bg-slate-50 p-3 text-sm"><div className="flex flex-wrap items-center gap-2"><Stars value={r.rating} /><HumanBadge /><span className="text-xs text-slate-500">{short(r.reviewer.wallet_address)} → {r.target_type === "agent" ? "PM Agent" : "発注者"}</span></div><p className="mt-1">{r.comment}</p></li>)}
        </ul>
      )}
      {(isClient || isWorker) && !mine && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-2 text-2xl">{[1, 2, 3, 4, 5].map((n) => <button key={n} onClick={() => setRating(n)} className={n <= rating ? "text-amber-500" : "text-slate-300"}>★</button>)}</div>
          <textarea className={inputCls} rows={2} placeholder="良いコミュニケーションでした！" value={comment} onChange={(e) => setComment(e.target.value)} />
          <WorldVerifyButton action="review" signal={c.id} label="World で人間確認してレビューを投稿" onVerified={async (p) => { await post.mutateAsync(p); }} />
          <ErrorBox error={err} />
        </div>
      )}
    </Card>
  );
}
