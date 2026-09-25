"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { use, useState } from "react";
import { useAccount, usePublicClient, useWriteContract } from "wagmi";
import { api, short, STATUS_LABEL, usdc, type CaseDetail, type Review, type Task } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { erc20Abi, escrowAbi } from "@/lib/contracts";
import { Markdown } from "@/components/markdown";
import { WorldVerifyButton } from "@/components/world-verify";
import { ApproveButton } from "@/components/approve-button";
import { ContractsPanel, EnsPanel, ProgressPanel, ReplanPanel, TeamPanel } from "@/components/case-panels";
import { Amount, BackLink, Badge, Button, Card, ErrorBox, HumanBadge, inputCls, KindTag, Mono, Stars, TxLink } from "@/components/ui";

const STEPS = ["planning", "awaiting_approval", "in_progress", "delivered", "completed"];

export default function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { me, config } = useAuth();
  const qc = useQueryClient();
  const { data: c } = useQuery({ queryKey: ["case", id], queryFn: () => api<CaseDetail>(`/cases/${id}`), refetchInterval: 3000 });
  const { data: reviews } = useQuery({ queryKey: ["case-reviews", id], queryFn: () => api<Review[]>(`/reviews/case/${id}`) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["case", id] }); qc.invalidateQueries({ queryKey: ["case-reviews", id] }); };
  if (!c) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  const isClient = me?.id === c.client.id;
  const isApprover = !!me && c.approvers.map((a) => a.toLowerCase()).includes(me.wallet_address);
  const stepIdx = Math.max(STEPS.indexOf(c.status), c.status === "disputed" || c.status === "resolved" ? 3 : 0);
  const mock = !config || config.mock.chain;

  return (
    <div className="space-y-6">
      <BackLink href="/cases">案件一覧</BackLink>
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2"><h1 className="text-2xl font-bold">{c.title}</h1><Badge status={c.status} /></div>
            <p className="mt-1 flex flex-wrap items-center gap-x-2 text-sm text-neutral-500"><span className="whitespace-nowrap">PM Agent: <Link href={`/agents/${c.agent.id}`} className="text-neutral-900 underline underline-offset-2">{c.agent.name}</Link></span><Mono>{c.agent.ens_name}</Mono><span className="whitespace-nowrap">発注者 <Mono>{short(c.client.wallet_address)}</Mono></span></p>
            {c.project_ens_name && <p className="mt-1 flex flex-wrap items-center gap-2 text-xs"><Mono className="text-neutral-900">{c.project_ens_name}</Mono><TxLink hash={c.project_ens_tx_hash} label="ENS" /></p>}
            {c.description && <p className="mt-2 whitespace-pre-wrap text-sm text-neutral-700">{c.description}</p>}
          </div>
          <div className="text-right"><div className="text-2xl font-bold"><Amount value={usdc(c.budget)} /></div><div className="whitespace-nowrap text-xs text-neutral-500">Escrow case <Mono>{c.escrow_case_id.slice(0, 10)}…</Mono></div><div className="whitespace-nowrap text-xs tabular-nums text-neutral-500">承認者 {c.approvers.length} 名 / 必要 {c.threshold}</div></div>
        </div>
        <ol className="mt-5 flex flex-wrap gap-2 text-xs">
          {STEPS.map((s, i) => (
            <li key={s} className={`whitespace-nowrap rounded-sm border px-3 py-1 tabular-nums ${i < stepIdx ? "border-neutral-900 bg-white text-neutral-900" : i === stepIdx ? "border-neutral-900 bg-neutral-900 text-white" : "border-neutral-200 text-neutral-400"}`}>{i + 1}. {STATUS_LABEL[s]}</li>
          ))}
        </ol>
        <div className="mt-3 flex flex-wrap gap-4"><TxLink hash={c.open_tx_hash} label="openCase" /></div>
        {c.error && <ErrorBox error={c.error} />}
      </Card>

      {c.status === "planning" && <Card><p className="animate-pulse text-sm">{c.agent.name} がタスクを分解し、チームを編成しています…</p></Card>}
      {c.status === "planning_failed" && isClient && <ReplanPanel c={c} onReplan={() => api(`/cases/${id}/replan`, { method: "POST" }).then(refresh)} />}

      {c.plan_json && (
        <Card>
          <h2 className="font-semibold">計画とチーム編成 <span className="text-xs font-normal text-neutral-500">PM Agent が生成</span></h2>
          <p className="mt-1 text-sm text-neutral-700">{c.plan_json.summary}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {c.plan_json.team?.map((m) => <span key={m.name} className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-sm border border-neutral-300 px-2 py-1 text-xs"><KindTag kind={m.kind} />{m.name}</span>)}
          </div>
          {c.status === "awaiting_approval" && isClient && <OpenCasePanel c={c} mock={mock} onDone={refresh} />}
        </Card>
      )}

      {c.tasks.length > 0 && <TeamPanel c={c} />}
      {c.tasks.length > 0 && <ContractsPanel c={c} />}
      {c.tasks.length > 0 && c.status !== "awaiting_approval" && <ProgressPanel c={c} />}
      {c.tasks.length > 0 && <TaskBoard c={c} canApprove={isApprover && ["in_progress", "delivered"].includes(c.status)} onDone={refresh} />}

      {["in_progress", "delivered"].includes(c.status) && isClient && <DisputePanel c={c} onDone={refresh} />}
      {c.status === "disputed" && <Card><p className="text-sm">紛争中です。未払いのタスクは Escrow に保留され、Jury の裁定でのみ動きます。 <Link className="text-neutral-900 underline" href={`/jury/${c.dispute_id}`}>Jury 画面へ</Link></p></Card>}
      {c.status === "resolved" && <Card><p className="text-sm">Human Jury の多数決で解決しました。 <Link className="text-neutral-900 underline" href={`/jury/${c.dispute_id}`}>結果を見る</Link></p></Card>}

      {c.tasks.length > 0 && <EnsPanel c={c} />}
      {(c.status === "completed" || c.status === "resolved") && me && <ReviewPanel c={c} reviews={reviews ?? []} meId={me.id} onDone={refresh} />}
    </div>
  );
}

/** UC-003: 発注者が openCase（承認者の固定）と USDC の approve を行い、worker が工程ごとに預託する */
function OpenCasePanel({ c, mock, onDone }: { c: CaseDetail; mock: boolean; onDone: () => void }) {
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
        setStep("Escrow.openCase に署名…");
        const h = await writeContractAsync({ address: escrow, abi: escrowAbi, functionName: "openCase", args: [c.escrow_case_id as `0x${string}`, token, c.approvers as `0x${string}`[], c.threshold] });
        setStep("トランザクション確認中…");
        await pc.waitForTransactionReceipt({ hash: h });
        txHash = h;
      }
      setStep("API に通知…");
      await api(`/cases/${c.id}/opened`, { method: "POST", json: { tx_hash: txHash } });
      onDone();
    } catch (e) {
      setErr(e);
    } finally {
      setStep(null);
    }
  };
  return (
    <div className="mt-4 rounded-md border border-neutral-900 p-4">
      <p className="text-sm">計画を承認すると、Escrow に案件を開き（承認者 {c.approvers.length} 名 / 必要 {c.threshold} を固定）、USDC の引き落としを許可します。そのあとチェーン連携ワーカーが<b>工程ごとに</b>資金を預けて作業が始まります。支払いは承認がそろった工程から自動で実行されます。</p>
      <div className="mt-3"><Button onClick={run} disabled={!!step}>{step ?? (mock ? "承認して Escrow を開く（モック）" : "承認して Escrow を開く")}</Button></div>
      <div className="mt-2"><ErrorBox error={err} /></div>
    </div>
  );
}

function TaskBoard({ c, canApprove, onDone }: { c: CaseDetail; canApprove: boolean; onDone: () => void }) {
  const { me } = useAuth();
  const [openId, setOpenId] = useState<string | null>(null);
  const tasks = c.tasks;
  const cols: [string, string, Task[]][] = [
    ["todo", "ToDo", tasks.filter((t) => t.status === "todo")],
    ["in_progress", "進行中", tasks.filter((t) => t.status === "in_progress")],
    ["done", "提出済み", tasks.filter((t) => t.status === "done")],
  ];
  const open = tasks.find((t) => t.id === openId);
  return (
    <div>
      <div className="grid gap-3 md:grid-cols-3">
        {cols.map(([k, label, list]) => (
          <div key={k} className="rounded-md border border-neutral-200 bg-neutral-100 p-3">
            <div className="mb-2 text-xs font-semibold text-neutral-600">{label} ({list.length})</div>
            <div className="space-y-2">
              {list.map((t) => (
                <button key={t.id} onClick={() => setOpenId(t.id === openId ? null : t.id)} className={`w-full rounded-md border bg-white p-3 text-left text-sm hover:border-neutral-900 ${openId === t.id ? "border-neutral-900 shadow-[2px_2px_0_0_#171717]" : "border-neutral-200"}`}>
                  <div className="flex min-w-0 items-center gap-2"><KindTag kind={t.type} /><span className="truncate font-medium">{t.title}</span></div>
                  <div className="mt-1 flex justify-between gap-2 text-xs text-neutral-500"><span className="truncate">{t.assignee_name}</span><Amount value={usdc(t.estimated_cost)} /></div>
                  <div className="mt-1 flex flex-wrap gap-1"><Badge status={`chain:${t.chain_status}`} />{t.type === "human" && t.human_task && <Badge status={t.human_task.status} />}{t.chain_status === "submitted" && <span className="whitespace-nowrap text-[11px] tabular-nums text-neutral-500">承認 {t.approval_count}/{c.threshold}</span>}</div>
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      {open && (
        <Card className="mt-3">
          <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="flex min-w-0 items-center gap-2 font-semibold"><KindTag kind={open.type} /><span>{open.title}</span></h3><div className="flex gap-2"><Badge status={open.status} /><Badge status={`chain:${open.chain_status}`} /></div></div>
          <p className="mt-1 text-sm text-neutral-600">{open.description}</p>
          <dl className="mt-2 grid gap-1 text-xs text-neutral-600 sm:grid-cols-2">
            <div>成果物ハッシュ: <span className="font-mono">{open.deliverable_hash ? open.deliverable_hash.slice(0, 18) + "…" : "未提出"}</span></div>
            <div>支払先: <span className="font-mono">{open.payee ? short(open.payee) : "-"}</span></div>
            <div>Escrow task: <span className="font-mono">{open.escrow_task_id?.slice(0, 18)}…</span></div>
            <div><TxLink hash={open.chain_tx_hash} label="最新 tx" /></div>
          </dl>
          {open.approvals.length > 0 && <ul className="mt-2 text-xs">{open.approvals.map((a) => <li key={a.id} className="flex items-center gap-2"><HumanBadge /> {short(a.approver.wallet_address)} が承認（{new Date(a.created_at).toLocaleString("ja-JP")}）</li>)}</ul>}
          {open.type === "human" && open.human_task && open.human_task.status !== "done" && (
            <p className="mt-2 text-sm">Human Task として指名・公開中 → <Link href={`/tasks/${open.human_task.id}`} className="text-neutral-900 underline">タスクページ</Link></p>
          )}
          {open.deliverable && <div className="mt-3 rounded-md border border-neutral-200 p-3"><Markdown>{open.deliverable}</Markdown></div>}
          {canApprove && open.chain_status === "submitted" && <div className="mt-3"><ApproveButton caseId={c.id} taskId={open.id} deliverableHash={open.deliverable_hash} approvalCount={open.approval_count} threshold={c.threshold} alreadyApproved={open.approvals.some((a) => a.approver.id === me?.id && a.deliverable_hash === open.deliverable_hash)} onDone={onDone} /></div>}
        </Card>
      )}
      {canApprove && tasks.some((t) => t.chain_status === "submitted") && (
        <p className="mt-2 text-xs text-neutral-500">承認者はカードを開いて各工程を承認します。必要数（{c.threshold}）がそろった工程から Escrow が自動で支払います。差し替えられた成果物への古い承認は無効になります。</p>
      )}
    </div>
  );
}

function DisputePanel({ c, onDone }: { c: CaseDetail; onDone: () => void }) {
  const [reason, setReason] = useState("");
  const [show, setShow] = useState(false);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const dispute = async () => {
    setBusy(true); setErr(null);
    try { await api(`/cases/${c.id}/dispute`, { method: "POST", json: { reason } }); onDone(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div><h2 className="font-semibold">納得できないとき</h2><p className="text-xs text-neutral-500">差し戻すと未払いの工程は Escrow に保留され、AI が論点を整理したうえで World で確認された第三者 3 名（Human Jury）の多数決で支払い / 返金が決まります。</p></div>
        <Button variant="danger" onClick={() => setShow((v) => !v)}>差し戻す</Button>
      </div>
      {show && (
        <div className="mt-3 space-y-2">
          <textarea className={inputCls} rows={3} placeholder="差し戻し理由（例: 約束した機能が足りない）" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button variant="danger" onClick={dispute} disabled={busy || !reason}>差し戻して Jury に回す</Button>
          <ErrorBox error={err} />
        </div>
      )}
    </Card>
  );
}

function ReviewPanel({ c, reviews, meId, onDone }: { c: CaseDetail; reviews: Review[]; meId: string; onDone: () => void }) {
  const [rating, setRating] = useState(5);
  const [comment, setComment] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const isClient = c.client.id === meId;
  const isWorker = c.tasks.some((t) => t.human_task?.worker?.id === meId);
  const mine = reviews.find((r) => r.reviewer.id === meId);
  return (
    <Card>
      <h2 className="font-semibold">Human-backed Review</h2>
      <p className="mt-1 text-xs text-neutral-500">案件の当事者（発注者 → PM Agent、Human Task worker → 発注者）が、World で人間確認をしてから評価します。Bot による水増しはできません。</p>
      {reviews.length > 0 && (
        <ul className="mt-3 space-y-2">
          {reviews.map((r) => <li key={r.id} className="rounded-md border border-neutral-200 p-3 text-sm"><div className="flex flex-wrap items-center gap-2"><Stars value={r.rating} /><HumanBadge /><span className="text-xs text-neutral-500">{short(r.reviewer.wallet_address)} → {r.target_type === "agent" ? "PM Agent" : "発注者"}</span></div><p className="mt-1">{r.comment}</p></li>)}
        </ul>
      )}
      {(isClient || isWorker) && !mine && (
        <div className="mt-4 space-y-2">
          <div className="flex items-center gap-2 text-2xl">{[1, 2, 3, 4, 5].map((n) => <button key={n} onClick={() => setRating(n)} className={n <= rating ? "text-neutral-700" : "text-neutral-300"}>★</button>)}</div>
          <textarea className={inputCls} rows={2} placeholder="良いコミュニケーションでした！" value={comment} onChange={(e) => setComment(e.target.value)} />
          <WorldVerifyButton action="review" signal={c.id} label="World で人間確認してレビューを投稿" onVerified={async (p) => { setErr(null); try { await api("/reviews", { method: "POST", json: { case_id: c.id, rating, comment, idkit_response: p } }); onDone(); } catch (e) { setErr(e); throw e; } }} />
          <ErrorBox error={err} />
        </div>
      )}
    </Card>
  );
}
