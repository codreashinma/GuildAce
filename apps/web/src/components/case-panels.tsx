"use client";

import { useState } from "react";
import { short, usdc, type Case, type Task } from "@/lib/api";
import { candidatesFor, contractFor, memberEnsFor, PERMISSIONS, projectSubname, reviewDeadline, type Candidate } from "@/lib/mock";
import { Badge, Card, HumanBadge } from "./ui";

const KIND = { company: "🏢 企業", ai: "🤖 AI Agent", human: "🧑 人間" };

/** UC-002 / FR-004 / FR-005: ENS から候補を検索してチームを編成（UI モック） */
export function TeamPanel({ c }: { c: Case }) {
  const [openRole, setOpenRole] = useState<string | null>(null);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">チーム編成 <span className="text-xs font-normal text-slate-500">PM Agent が ENS から候補を検索して編成</span></h2>
        <span className="font-mono text-xs text-blue-700">{projectSubname(c)}</span>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {c.tasks.map((t) => {
          const ht = t.human_task;
          const ens = ht?.assignee ? ht.assignee.ens_name : ht && ht.status !== "assigned" && ht.worker ? `worker ${short(ht.worker.wallet_address)}` : memberEnsFor(t, c.agent.label);
          const name = ht?.assignee ? `${ht.assignee.name}（${ht.assignee.role}）` : t.assignee_name;
          return (
            <div key={t.id} className="rounded-lg border border-slate-200 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2"><span>{t.type === "human" ? "🧑" : "🤖"}</span><b>{name}</b>{ht && <Badge status={ht.status} />}</div>
                <span className="font-semibold">{usdc(t.estimated_cost)} USDC</span>
              </div>
              <div className="mt-1 font-mono text-xs text-blue-700">{ens}</div>
              <div className="mt-1 text-xs text-slate-500">担当: {t.title}</div>
              {ht?.assignment_reason && <div className="mt-1 rounded bg-amber-50 px-2 py-1 text-xs text-amber-900">🤖 PM Agent の指名理由: {ht.assignment_reason}</div>}
              <button className="mt-2 text-xs text-slate-600 underline" onClick={() => setOpenRole(openRole === t.id ? null : t.id)}>{openRole === t.id ? "候補を閉じる" : "ENS で探した候補を見る"}</button>
              {openRole === t.id && <CandidateList items={candidatesFor(t.role)} chosen={ens} />}
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function CandidateList({ items, chosen }: { items: Candidate[]; chosen: string }) {
  return (
    <ul className="mt-2 space-y-1 rounded-lg bg-slate-50 p-2">
      {items.map((x) => (
        <li key={x.ens} className={`flex flex-wrap items-center gap-2 rounded-md px-2 py-1 text-xs ${x.ens === chosen ? "bg-blue-100" : ""}`}>
          <span className="font-mono text-blue-700">{x.ens}</span><span>{KIND[x.kind]}</span>
          <span className="text-amber-600">★{x.rating.toFixed(1)} ({x.reviews} Human)</span>
          <span className="text-slate-500">実績 {x.completed}</span><span className="ml-auto">{x.price} USDC〜</span>
          {x.ens === chosen && <span className="rounded bg-blue-600 px-1.5 text-[10px] text-white">選定</span>}
        </li>
      ))}
    </ul>
  );
}

/** UC-003 / FR-006 / FR-007 / CON-006: タスク別契約と工程ごとの預託 */
export function ContractsPanel({ c }: { c: Case }) {
  const [open, setOpen] = useState<string | null>(null);
  const funded = !!c.deposit_tx_hash;
  const total = c.tasks.reduce((s, t) => s + Number(t.estimated_cost), 0);
  const fee = Number(c.budget) - total;
  return (
    <Card>
      <h2 className="font-semibold">契約と Escrow <span className="text-xs font-normal text-slate-500">タスク（工程）単位で契約し、資金を預ける</span></h2>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500"><tr><th className="py-1">契約</th><th>タスク</th><th>受注側</th><th className="text-right">金額</th><th>預託</th><th>状態</th></tr></thead>
          <tbody>
            {c.tasks.map((t) => {
              const ct = contractFor(t);
              return (
                <>
                  <tr key={t.id} className="cursor-pointer border-t border-slate-100 hover:bg-slate-50" onClick={() => setOpen(open === t.id ? null : t.id)}>
                    <td className="py-2 font-mono text-xs">{ct.id}</td><td>{t.title}</td>
                    <td className="font-mono text-xs text-blue-700">{memberEnsFor(t, c.agent.label)}</td>
                    <td className="text-right">{usdc(t.estimated_cost)}</td>
                    <td>{funded ? <span className="text-emerald-700">🔒 預託済</span> : <span className="text-slate-400">未</span>}</td>
                    <td><Badge>{ct.status}</Badge></td>
                  </tr>
                  {open === t.id && (
                    <tr key={t.id + "x"}><td colSpan={6} className="bg-slate-50 px-3 py-2 text-xs text-slate-700"><ul className="list-disc pl-4">{ct.terms.map((x) => <li key={x}>{x}</li>)}</ul></td></tr>
                  )}
                </>
              );
            })}
            <tr className="border-t border-slate-200 text-xs text-slate-500"><td className="py-2" colSpan={3}>PM Agent 手数料（{c.agent.fee_bps / 100}%）</td><td className="text-right">{usdc(fee)}</td><td colSpan={2}></td></tr>
            <tr className="font-semibold"><td className="py-2" colSpan={3}>合計（Escrow 預託額）</td><td className="text-right">{usdc(c.budget)} USDC</td><td colSpan={2}>{funded ? "🔒 Escrow 保管中" : ""}</td></tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-slate-500">資金は契約条件（検収承認）を満たすまでスマートコントラクトの外に出ません。期限の到来や AI の判断では動きません。</p>
    </Card>
  );
}

/** FR-008: 進捗管理 */
export function ProgressPanel({ c }: { c: Case }) {
  const done = c.tasks.filter((t) => t.status === "done").length;
  const pct = c.tasks.length ? Math.round((done / c.tasks.length) * 100) : 0;
  const dl = reviewDeadline(c);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">進捗 <span className="text-xs font-normal text-slate-500">PM Agent が管理</span></h2>
        <div className="text-xs text-slate-500">納期 {c.deadline ?? "未指定"} · 検収期限（仮 7 日）{dl.label}{c.status === "delivered" && <span className="ml-1 text-rose-600">あと {dl.days} 日</span>}</div>
      </div>
      <div className="mt-3 h-2 w-full rounded-full bg-slate-100"><div className="h-2 rounded-full bg-emerald-500 transition-all" style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 text-xs text-slate-500">{done}/{c.tasks.length} タスク完了（{pct}%）</div>
      <ol className="mt-3 space-y-1 text-sm">
        {c.tasks.map((t) => (
          <li key={t.id} className="flex items-center gap-2">
            <span className={`h-2 w-2 rounded-full ${t.status === "done" ? "bg-emerald-500" : t.status === "in_progress" ? "animate-pulse bg-amber-500" : "bg-slate-300"}`} />
            <span className="flex-1">{t.title}</span>
            <span className="text-xs text-slate-500">{t.assignee_name}</span>
            {t.completed_at && <span className="text-xs text-slate-400">{new Date(t.completed_at).toLocaleString("ja-JP")}</span>}
          </li>
        ))}
      </ol>
    </Card>
  );
}

function ApproverRow({ label, desc, ok, done, onClick, disabled }: { label: string; desc: string; ok: boolean; done: boolean; onClick: () => void; disabled?: boolean }) {
  return (
    <li className="flex flex-wrap items-center gap-3 rounded-lg border border-slate-200 p-3 text-sm">
      <div className="flex-1"><div className="font-medium">{label}</div><div className="text-xs text-slate-500">{desc}</div></div>
      {ok || done ? <span className="flex items-center gap-2 text-emerald-700"><HumanBadge />承認済み</span> : (
        <button disabled={disabled} onClick={onClick} className="rounded-lg bg-slate-900 px-3 py-1.5 text-xs text-white disabled:bg-slate-300">◎ World で人間確認して承認</button>
      )}
    </li>
  );
}

/** UC-005 / FR-010 / FR-011: 発注者側の承認者（開発部 → 経理部）と World による人間確認（UI モック） */
export function ApproverPanel({ c, onAllApproved }: { c: Case; onAllApproved: (ok: boolean) => void }) {
  const [dev, setDev] = useState(false);
  const [fin, setFin] = useState(false);
  const done = c.status !== "delivered";
  const toggleDev = () => { setDev(true); };
  const toggleFin = () => { setFin(true); onAllApproved(true); };
  return (
    <Card>
      <h2 className="font-semibold">承認フロー <span className="text-xs font-normal text-slate-500">重要な承認では毎回、人間であることの確認と内容への署名を行う</span></h2>
      <ol className="mt-3 space-y-2">
        <ApproverRow label="1. 開発部（検収の承認）" desc="成果物が約束どおりの内容か確認する" ok={dev} done={done} onClick={toggleDev} />
        <ApproverRow label="2. 経理部（支払の承認）" desc="検収済みの内容と支払額を承認する" ok={fin} done={done} onClick={toggleFin} disabled={!dev} />
      </ol>
      <p className="mt-2 text-xs text-slate-500">名前と権限は別のもの。部署名があるだけでは承認できず、会社の管理者が担当者に付与した権限（ENSv2 EAC）を Escrow が確認します。</p>
    </Card>
  );
}

/** FR-027 / FR-028: プロジェクト subname と ENSv2 の権限 */
export function EnsPanel({ c }: { c: Case }) {
  const agentName = c.agent.ens_name ?? `${c.agent.label}.choice.eth`;
  const creator = c.agent.creator.display_name ? `${c.agent.creator.display_name}（${short(c.agent.creator.wallet_address)}）` : short(c.agent.creator.wallet_address);
  return (
    <Card>
      <h2 className="font-semibold">ENS <span className="text-xs font-normal text-slate-500">プロジェクトの名前と権限（ENSv2 EAC）</span></h2>
      <div className="mt-2 rounded-lg bg-slate-50 p-3 font-mono text-xs">
        <div>{c.agent.creator.display_name ?? short(c.agent.creator.wallet_address)} <span className="text-slate-400">(Creator)</span></div>
        <div>└─ <span className="text-blue-700">{agentName}</span> <span className="text-slate-400">(PM Agent)</span></div>
        <div>&nbsp;&nbsp;&nbsp;&nbsp;└─ <span className="text-blue-700">{projectSubname(c)}</span> <span className="text-slate-400">(この案件)</span></div>
        {c.tasks.map((t) => <div key={t.id}>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;├─ {t.role}.{projectSubname(c)}</div>)}
      </div>
      <table className="mt-3 w-full text-xs">
        <thead className="text-left text-slate-500"><tr><th className="py-1">ロール</th><th>名前</th><th>できること</th></tr></thead>
        <tbody>{PERMISSIONS.map((p) => <tr key={p.role} className="border-t border-slate-100"><td className="py-1 font-medium">{p.role}</td><td className="font-mono text-blue-700">{p.ens(agentName, creator)}</td><td>{p.can}</td></tr>)}</tbody>
      </table>
    </Card>
  );
}

/** FR-033: 編成不能時の再確認 */
export function ReplanPanel({ c, onReplan }: { c: Case; onReplan: () => void }) {
  return (
    <Card className="border-amber-200 bg-amber-50">
      <h2 className="font-semibold">条件の再確認が必要です</h2>
      <p className="mt-1 text-sm">PM Agent が予算内でチームを編成できませんでした。{c.error && <span className="text-rose-700">（{c.error}）</span>}</p>
      <ul className="mt-2 list-disc pl-5 text-sm text-slate-700"><li>予算を増やす</li><li>納期を延ばす</li><li>依頼の範囲を絞る（例: 現地撮影を外す）</li></ul>
      <button onClick={onReplan} className="mt-3 rounded-lg bg-slate-900 px-4 py-2 text-sm text-white">条件を見直して再計画する</button>
    </Card>
  );
}

export function TaskBadge({ t }: { t: Task }) {
  return <Badge status={t.status} />;
}
