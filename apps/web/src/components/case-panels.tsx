"use client";

import { Fragment, useState } from "react";
import { short, usdc, type Case, type Task } from "@/lib/api";
import { candidatesFor, contractFor, memberEnsFor, PERMISSIONS, projectSubname, reviewDeadline, type Candidate } from "@/lib/mock";
import { Amount, Badge, Card, KindTag, Mono } from "./ui";



/** UC-002 / FR-004 / FR-005: ENS から候補を検索してチームを編成（UI モック） */
export function TeamPanel({ c }: { c: Case }) {
  const [openRole, setOpenRole] = useState<string | null>(null);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">チーム編成 <span className="text-xs font-normal text-neutral-500">PM Agent が ENS から候補を検索して編成</span></h2>
        <Mono className="text-neutral-900">{c.project_ens_name ?? projectSubname(c)}</Mono>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {c.tasks.map((t) => {
          const ht = t.human_task;
          const ens = ht?.assignee ? ht.assignee.ens_name : ht && ht.status !== "assigned" && ht.worker ? `worker ${short(ht.worker.wallet_address)}` : memberEnsFor(t, c.agent.label);
          const name = ht?.assignee ? `${ht.assignee.name}（${ht.assignee.role}）` : t.assignee_name;
          return (
            <div key={t.id} className="rounded-md border border-neutral-200 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2"><KindTag kind={t.type} /><b className="truncate">{name}</b>{ht && <Badge status={ht.status} />}</div>
                <Amount value={usdc(t.estimated_cost)} className="font-semibold" />
              </div>
              <div className="mt-1"><Mono className="text-neutral-900">{ens}</Mono></div>
              <div className="mt-1 text-xs text-neutral-500">担当: {t.title}</div>
              {ht?.assignment_reason && <div className="mt-1 rounded bg-neutral-100 px-2 py-1 text-xs text-neutral-900">PM Agent の指名理由: {ht.assignment_reason}</div>}
              <button className="mt-2 text-xs text-neutral-600 underline" onClick={() => setOpenRole(openRole === t.id ? null : t.id)}>{openRole === t.id ? "候補を閉じる" : "ENS で探した候補を見る"}</button>
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
    <ul className="mt-2 space-y-1 rounded-md border border-neutral-200 p-2">
      {items.map((x) => (
        <li key={x.ens} className={`flex flex-wrap items-center gap-2 rounded-md px-2 py-1 text-xs ${x.ens === chosen ? "bg-neutral-100" : ""}`}>
          <Mono className="text-neutral-900">{x.ens}</Mono><KindTag kind={x.kind} />
          <span className="whitespace-nowrap tabular-nums">★{x.rating.toFixed(1)} ({x.reviews} Human)</span>
          <span className="whitespace-nowrap text-neutral-500">実績 {x.completed}</span><span className="ml-auto whitespace-nowrap tabular-nums">{x.price} USDC〜</span>
          {x.ens === chosen && <span className="whitespace-nowrap rounded-sm bg-neutral-900 px-1.5 text-[10px] text-white">選定</span>}
        </li>
      ))}
    </ul>
  );
}

/** UC-003 / FR-006 / FR-007 / CON-006: タスク別契約と工程ごとの預託 */
export function ContractsPanel({ c }: { c: Case }) {
  const [open, setOpen] = useState<string | null>(null);
  const total = c.tasks.reduce((s, t) => s + Number(t.estimated_cost), 0);
  return (
    <Card>
      <h2 className="font-semibold">契約と Escrow <span className="text-xs font-normal text-neutral-500">タスク（工程）単位で契約し、資金を預ける</span></h2>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">契約</th><th className="pr-3">タスク</th><th className="pr-3">受注側</th><th className="pr-3 text-right">金額</th><th className="pr-3">預託</th><th>状態</th></tr></thead>
          <tbody>
            {c.tasks.map((t) => {
              const ct = contractFor(t);
              return (
                <Fragment key={t.id}>
                  <tr className="cursor-pointer border-t border-neutral-100 align-top hover:bg-neutral-50 [&>td]:pr-3 [&>td]:py-2" onClick={() => setOpen(open === t.id ? null : t.id)}>
                    <td className="whitespace-nowrap py-2 font-mono text-xs">{ct.id}</td><td className="min-w-40">{t.title}</td>
                    <td><Mono className="text-neutral-900">{memberEnsFor(t, c.agent.label)}</Mono></td>
                    <td className="whitespace-nowrap text-right tabular-nums">{usdc(t.estimated_cost)}</td>
                    <td>{t.chain_status === "none" ? <span className="text-neutral-400">未</span> : <span className="whitespace-nowrap text-neutral-900">{t.chain_status === "paid" ? "支払済" : t.chain_status === "resolved" ? "裁定済" : "預託中"}</span>}</td>
                    <td><Badge status={`chain:${t.chain_status}`} /></td>
                  </tr>
                  {open === t.id && (
                    <tr><td colSpan={6} className="bg-neutral-50 px-3 py-2 text-xs text-neutral-700"><ul className="list-disc pl-4">{ct.terms.map((x) => <li key={x}>{x}</li>)}</ul></td></tr>
                  )}
                </Fragment>
              );
            })}
            <tr className="border-t border-neutral-200 font-semibold"><td className="py-2" colSpan={3}>合計（工程ごとに預託。PM 管理費 {c.agent.fee_bps / 100}% を含む）</td><td className="whitespace-nowrap text-right"><Amount value={usdc(total)} /></td><td colSpan={2}></td></tr>
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-neutral-500">資金は工程ごとに Escrow が保持し、承認者の承認が必要数そろった工程から自動で支払われます。オフチェーンから送金を指示する経路はありません。期限の到来や AI の判断では動きません。</p>
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
        <h2 className="font-semibold">進捗 <span className="text-xs font-normal text-neutral-500">PM Agent が管理</span></h2>
        <div className="flex flex-wrap gap-x-3 text-xs tabular-nums text-neutral-500"><span className="whitespace-nowrap">納期 {c.deadline ?? "未指定"}</span><span className="whitespace-nowrap">検収期限（仮 7 日）{dl.label}</span>{c.status === "delivered" && <span className="whitespace-nowrap text-neutral-900">あと {dl.days} 日</span>}</div>
      </div>
      <div className="mt-3 h-1.5 w-full bg-neutral-200"><div className="h-1.5 bg-neutral-900 transition-all" style={{ width: `${pct}%` }} /></div>
      <div className="mt-1 whitespace-nowrap text-xs tabular-nums text-neutral-500">{done}/{c.tasks.length} タスク完了（{pct}%）</div>
      <ol className="mt-3 space-y-1 text-sm">
        {c.tasks.map((t) => (
          <li key={t.id} className="flex items-center gap-2">
            <span className={`h-2 w-2 shrink-0 ${t.status === "done" ? "bg-neutral-900" : t.status === "in_progress" ? "animate-pulse border border-neutral-900" : "border border-neutral-300"}`} />
            <span className="min-w-0 flex-1 truncate">{t.title}</span>
            <span className="hidden whitespace-nowrap text-xs text-neutral-500 sm:inline">{t.assignee_name}</span>
            {t.completed_at && <span className="whitespace-nowrap text-xs tabular-nums text-neutral-400">{new Date(t.completed_at).toLocaleString("ja-JP", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" })}</span>}
          </li>
        ))}
      </ol>
    </Card>
  );
}

/** FR-027 / FR-028: プロジェクト subname と ENSv2 の権限 */
export function EnsPanel({ c }: { c: Case }) {
  const agentName = c.agent.ens_name ?? `${c.agent.label}.choice.eth`;
  const creator = c.agent.creator.display_name ? `${c.agent.creator.display_name}（${short(c.agent.creator.wallet_address)}）` : short(c.agent.creator.wallet_address);
  return (
    <Card>
      <h2 className="font-semibold">ENS <span className="text-xs font-normal text-neutral-500">プロジェクトの名前と権限（ENSv2 EAC）</span></h2>
      <div className="mt-2 overflow-x-auto whitespace-nowrap rounded-md bg-neutral-100 p-3 font-mono text-xs leading-6">
        <div>{c.agent.creator.display_name ?? short(c.agent.creator.wallet_address)} <span className="text-neutral-400">(Creator)</span></div>
        <div>└─ <span className="text-neutral-900">{agentName}</span> <span className="text-neutral-400">(PM Agent)</span></div>
        <div>&nbsp;&nbsp;&nbsp;&nbsp;└─ <span className="text-neutral-900">{c.project_ens_name ?? projectSubname(c)}</span> <span className="text-neutral-400">(この案件{c.project_ens_name ? "・発行済" : "・openCase 後に発行"})</span></div>
      </div>
      <table className="mt-3 w-full text-xs">
        <thead className="text-left text-neutral-500"><tr><th className="py-1">ロール</th><th>名前</th><th>できること</th></tr></thead>
        <tbody>{PERMISSIONS.map((p) => <tr key={p.role} className="border-t border-neutral-100 align-top"><td className="whitespace-nowrap py-1 pr-3 font-medium">{p.role}</td><td className="pr-3"><Mono className="text-neutral-900">{p.ens(agentName, creator)}</Mono></td><td>{p.can}</td></tr>)}</tbody>
      </table>
    </Card>
  );
}

/** FR-033: 編成不能時の再確認 */
export function ReplanPanel({ c, onReplan }: { c: Case; onReplan: () => void }) {
  return (
    <Card className="border-neutral-300 bg-neutral-100">
      <h2 className="font-semibold">条件の再確認が必要です</h2>
      <p className="mt-1 text-sm">PM Agent が予算内でチームを編成できませんでした。{c.error && <span className="text-neutral-900">（{c.error}）</span>}</p>
      <ul className="mt-2 list-disc pl-5 text-sm text-neutral-700"><li>予算を増やす</li><li>納期を延ばす</li><li>依頼の範囲を絞る（例: 現地撮影を外す）</li></ul>
      <button onClick={onReplan} className="mt-3 whitespace-nowrap rounded-md bg-neutral-900 px-4 py-2 text-sm text-white">条件を見直して再計画する</button>
    </Card>
  );
}

export function TaskBadge({ t }: { t: Task }) {
  return <Badge status={t.status} />;
}
