"use client";

import { Fragment, useState } from "react";
import { usdc, type Case, type Task } from "@/lib/api";
import { useQuery } from "@tanstack/react-query";
import { api, type AgentDetail, type TeamCandidate, type TeamTask } from "@/lib/api";
import { contractFor, projectSubname, reviewDeadline } from "@/lib/mock";
import { EnsRolesTable } from "./ens-roles";
import { Amount, Badge, Card, KindTag, Mono } from "./ui";



/** UC-002 / FR-004 / FR-005: チーム編成。AI は Agent 名前空間の subname、人間は ENS に登録された会社の人員（API /cases/{id}/team の実データ） */
export function TeamPanel({ c }: { c: Case }) {
  const { data: team } = useQuery({ queryKey: ["team", c.id], queryFn: () => api<TeamTask[]>(`/cases/${c.id}/team`), refetchInterval: 8000 });
  const [openId, setOpenId] = useState<string | null>(null);
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="font-semibold">チーム編成 <span className="text-xs font-normal text-neutral-500">PM Agent が ENS の名前空間と人員レコードから編成</span></h2>
        <Mono className="text-neutral-900">{c.project_ens_name ?? projectSubname(c)}</Mono>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {(team ?? []).map((t) => {
          const recs = Object.entries(t.assignee_records);
          return (
            <div key={t.task_id} className="rounded-md border border-neutral-200 p-3 text-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="flex min-w-0 items-center gap-2"><KindTag kind={t.kind} /><b className="truncate">{t.assignee_name ?? "未定"}</b></div>
                <Amount value={usdc(t.amount)} className="font-semibold" />
              </div>
              <div className="mt-1">{t.assignee_ens ? <Mono className="text-neutral-900">{t.assignee_ens}</Mono> : <span className="text-xs text-neutral-500">指名待ち / 公開募集</span>}</div>
              <div className="mt-1 text-xs text-neutral-500">担当: {t.title}</div>
              {recs.length > 0 && (
                <dl className="mt-1 space-y-0.5 text-[11px] text-neutral-600">{recs.map(([k, v]) => <div key={k} className="grid grid-cols-[9rem_1fr] gap-1"><dt className="truncate font-mono text-neutral-400" title={k}>{k}</dt><dd className="truncate" title={v}>{v}</dd></div>)}</dl>
              )}
              {t.assignment_reason && <div className="mt-1 rounded bg-neutral-100 px-2 py-1 text-xs text-neutral-900">PM Agent の指名理由: {t.assignment_reason}</div>}
              {t.kind === "human" && t.candidates.length > 0 && (
                <>
                  <button className="mt-2 text-xs text-neutral-600 underline" onClick={() => setOpenId(openId === t.task_id ? null : t.task_id)}>{openId === t.task_id ? "候補を閉じる" : `ENS 上の人員 ${t.candidates.length} 名を見る`}</button>
                  {openId === t.task_id && <CandidateList items={t.candidates} />}
                </>
              )}
            </div>
          );
        })}
        {team && team.length === 0 && <p className="text-sm text-neutral-500">タスクがまだありません</p>}
      </div>
    </Card>
  );
}

function CandidateList({ items }: { items: TeamCandidate[] }) {
  return (
    <ul className="mt-2 space-y-1 rounded-md border border-neutral-200 p-2">
      {items.map((x) => (
        <li key={x.ens_name} className={`flex flex-wrap items-center gap-2 rounded-sm px-2 py-1 text-xs ${x.chosen ? "bg-neutral-900 text-white" : x.declined || !x.available ? "text-neutral-400" : ""}`}>
          <span className="font-mono">{x.ens_name}</span><span className="whitespace-nowrap">{x.name} / {x.role}</span>
          <span className={x.chosen ? "text-neutral-300" : "text-neutral-500"}>{x.skills}</span><span className="whitespace-nowrap">{x.location}</span>
          {x.company && <span className={`whitespace-nowrap ${x.chosen ? "text-neutral-300" : "text-neutral-500"}`}>{x.company}</span>}
          {x.chosen && <span className="ml-auto whitespace-nowrap rounded-sm border border-white px-1.5 text-[10px]">指名</span>}
          {x.declined && <span className="ml-auto whitespace-nowrap">辞退</span>}
          {!x.available && !x.declined && <span className="ml-auto whitespace-nowrap">稼働不可</span>}
        </li>
      ))}
    </ul>
  );
}

/** UC-003 / FR-006 / FR-007 / CON-006: タスク別契約と工程ごとの預託 */
export function ContractsPanel({ c }: { c: Case }) {
  const [open, setOpen] = useState<string | null>(null);
  const { data: team } = useQuery({ queryKey: ["team", c.id], queryFn: () => api<TeamTask[]>(`/cases/${c.id}/team`), refetchInterval: 8000 });
  const ensOf = (taskId: string) => team?.find((t) => t.task_id === taskId)?.assignee_ens ?? "未定";
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
                    <td><Mono className="text-neutral-900">{ensOf(t.id)}</Mono></td>
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
  const { data: agent } = useQuery({ queryKey: ["agent", c.agent.id], queryFn: () => api<AgentDetail>(`/agents/${c.agent.id}`), staleTime: 60_000 });
  return (
    <>
    <Card>
      <h2 className="font-semibold">ENS <span className="text-xs font-normal text-neutral-500">プロジェクトの名前と権限（ENSv2 EAC）</span></h2>
      <div className="mt-2 overflow-x-auto whitespace-nowrap rounded-md bg-neutral-100 p-3 font-mono text-xs leading-6">
        <div>{c.agent.creator.display_name ?? `${c.agent.creator.wallet_address.slice(0, 6)}…${c.agent.creator.wallet_address.slice(-4)}`} <span className="text-neutral-400">(Creator)</span></div>
        <div>└─ <span className="text-neutral-900">{agentName}</span> <span className="text-neutral-400">(PM Agent)</span></div>
        <div>&nbsp;&nbsp;&nbsp;&nbsp;└─ <span className="text-neutral-900">{c.project_ens_name ?? projectSubname(c)}</span> <span className="text-neutral-400">(この案件{c.project_ens_name ? "・発行済" : "・openCase 後に発行"})</span></div>
      </div>
    </Card>
    <EnsRolesTable roles={agent?.ens_roles ?? []} subregistry={agent?.ens_subregistry} />
    </>
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
