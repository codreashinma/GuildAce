"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { use } from "react";
import { api, short, usdc, type AuditEvent, type CaseAudit } from "@/lib/api";
import { BackLink, Badge, Card, EnsLink, Mono, PageTitle, TxLink } from "@/components/ui";

const ROLE: Record<string, string> = {
  client: "発注者", approver: "承認者", payee: "支払先", worker: "チェーン連携ワーカー（サーバー鍵）", "project-key": "Project 鍵", "owner-key": "Owner 鍵", creator: "Creator", jury: "Jury",
};
const JOB_STATUS: Record<string, string> = { done: "確定", recorded: "確定", queued: "送信待ち", running: "送信中", retry: "再送待ち", failed: "失敗", open: "審議中", closed: "裁定済" };

/** G2: 監査ビュー。案件の tx（openCase / fund / submit / approve / pay / dispute / resolve）と ENS 発行を時系列に並べ、
 *  関わったアドレスをプラットフォームが発行した ENS 名で示す（GET /cases/{id}/audit）。認証不要・第三者向け */
export default function CaseAuditPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data: a, error } = useQuery({ queryKey: ["case-audit", id], queryFn: () => api<CaseAudit>(`/cases/${id}/audit`), refetchInterval: 8000 });
  if (error) return <p className="text-sm text-neutral-700">読み込みに失敗しました: {(error as Error).message}</p>;
  if (!a) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  const name = (addr: string | null) => {
    if (!addr) return null;
    const hit = a.actors[addr.toLowerCase()];
    return hit?.name ? <span className="inline-flex items-center gap-1" title={addr}><EnsLink name={hit.name} />{!hit.verified && <span className="text-[10px] text-neutral-400">(未書込)</span>}</span> : <span title={addr}><Mono>{short(addr)}</Mono></span>;
  };
  return (
    <div className="space-y-6">
      <BackLink href={`/cases/${id}`}>案件に戻る</BackLink>
      <PageTitle title="監査ビュー" sub="案件に関わるオンチェーン tx と ENS への発行を時系列で並べています。資金の正本は Escrow コントラクト、名前の正本は ENS（Sepolia）です。署名や World ID の nullifier は表示しません。" />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2"><h2 className="text-lg font-semibold">{a.title}</h2><Badge status={a.status} /></div>
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-xs text-neutral-600 sm:grid-cols-[auto_1fr]">
              <dt className="whitespace-nowrap">Escrow case</dt><dd><Mono className="text-neutral-900">{a.escrow_case_id}</Mono></dd>
              <dt className="whitespace-nowrap">PM Agent（ENS）</dt><dd>{a.agent_ens_name ? <EnsLink name={a.agent_ens_name} /> : <span className="text-neutral-400">未公開</span>}</dd>
              <dt className="whitespace-nowrap">案件の subname</dt><dd>{a.project_ens_name ? <EnsLink name={a.project_ens_name} /> : <span className="text-neutral-400">未発行</span>}</dd>
              <dt className="whitespace-nowrap">承認者 / 必要数</dt>
              <dd className="flex flex-wrap items-center gap-2"><span className="tabular-nums">{a.approvers.length} 名 / {a.threshold}</span>{a.approvers.map((ap) => <span key={ap}>{name(ap)}</span>)}</dd>
            </dl>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-right text-xs text-neutral-500 sm:grid-cols-4">
            <Stat label="イベント" value={a.counts.events} /><Stat label="オンチェーン tx" value={a.counts.onchain} /><Stat label="失敗" value={a.counts.failed} /><Stat label="ENS 名で表示" value={a.counts.named_actors} />
          </div>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold">関わったアドレス <span className="text-xs font-normal text-neutral-500">ENS 逆引き（GET /ens/reverse と同じ規則。人員・Agent 受取・会社管理者の名前から引く）</span></h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">ENS 名</th><th className="pr-3">アドレス</th><th>役割</th></tr></thead>
            <tbody>
              {Object.values(a.actors).map((x) => (
                <tr key={x.address} className="border-t border-neutral-100 [&>td]:py-2 [&>td]:pr-3">
                  <td>{x.name ? <span className="inline-flex items-center gap-1"><EnsLink name={x.name} />{!x.verified && <span className="text-[10px] text-neutral-400">(未書込)</span>}</span> : <span className="text-neutral-400">名前なし</span>}</td>
                  <td><Mono>{x.address}</Mono></td>
                  <td className="flex flex-wrap gap-1">{x.roles.map((r) => <Badge key={r}>{ROLE[r] ?? r}</Badge>)}</td>
                </tr>
              ))}
              {Object.keys(a.actors).length === 0 && <tr><td colSpan={3} className="py-3 text-neutral-400">まだありません</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <h2 className="font-semibold">時系列 <span className="text-xs font-normal text-neutral-500">worker の tx は chain_jobs（冪等キー・再送）から、openCase は発注者の tx を検証して記録したもの</span></h2>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">#</th><th className="pr-3">時刻</th><th className="pr-3">イベント</th><th className="pr-3">タスク</th><th className="pr-3">実行者</th><th className="pr-3">tx</th><th>状態</th></tr></thead>
            <tbody>
              {a.events.map((e) => (
                <tr key={e.seq} className="border-t border-neutral-100 align-top [&>td]:py-2 [&>td]:pr-3">
                  <td className="tabular-nums text-neutral-500">{e.seq}</td>
                  <td className="whitespace-nowrap tabular-nums text-xs text-neutral-500">{e.at ? new Date(e.at).toLocaleString("ja-JP") : "—"}</td>
                  <td><div>{e.label}</div><Detail e={e} name={name} /></td>
                  <td className="min-w-32 text-xs">{e.task_title ?? <span className="text-neutral-400">案件全体</span>}</td>
                  <td className="text-xs"><div className="text-neutral-500">{ROLE[e.actor_role] ?? e.actor_role}</div>{e.actor && <div>{name(e.actor)}</div>}</td>
                  <td>{e.tx_hash ? <TxLink hash={e.tx_hash} label={e.mock ? "mock" : "tx"} /> : <span className="text-xs text-neutral-400">—</span>}</td>
                  <td><Badge status={e.status === "failed" ? "publish_failed" : e.status === "done" || e.status === "recorded" ? "done" : undefined}>{JOB_STATUS[e.status] ?? e.status}</Badge></td>
                </tr>
              ))}
              {a.events.length === 0 && <tr><td colSpan={7} className="py-3 text-neutral-400">まだオンチェーンの記録はありません</td></tr>}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-neutral-500">Etherscan の tx リンクから Escrow の入出金を、<Link className="underline" href="/ens">/ens</Link> から名前の実レコードを、それぞれ正本側で確認できます。</p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div><div className="text-lg font-semibold tabular-nums text-neutral-900">{value}</div><div className="whitespace-nowrap">{label}</div></div>;
}

function Detail({ e, name }: { e: AuditEvent; name: (a: string | null) => React.ReactNode }) {
  const d = e.detail;
  const items: React.ReactNode[] = [];
  if (typeof d.amount === "string") items.push(<span key="amt" className="whitespace-nowrap">金額 {usdc(d.amount)} USDC</span>);
  if (typeof d.pay_amount === "string") items.push(<span key="pay" className="whitespace-nowrap">解放 {usdc(d.pay_amount)} / 返金 {usdc(String(d.refund_amount ?? "0"))} USDC</span>);
  if (typeof d.approval_count === "number") items.push(<span key="cnt" className="whitespace-nowrap tabular-nums">承認 {d.approval_count} / {String(d.threshold ?? "?")}</span>);
  if (typeof d.deliverable_hash === "string") items.push(<span key="h" className="whitespace-nowrap">成果物 <Mono>{short(d.deliverable_hash)}</Mono></span>);
  if (typeof d.payee === "string") items.push(<span key="p" className="whitespace-nowrap">支払先 {name(d.payee)}</span>);
  if (typeof d.ens_name === "string") items.push(<span key="e"><EnsLink name={d.ens_name} /></span>);
  if (Array.isArray(d.voters)) items.push(<span key="v" className="flex flex-wrap gap-1">投票 {d.voters.map((v) => <span key={String(v)}>{name(String(v))}</span>)}</span>);
  if (typeof d.outcome === "string") items.push(<span key="o">結果 {d.outcome === "release" ? "解放" : "返金"}</span>);
  if (typeof d.error === "string") items.push(<span key="err" className="text-neutral-700">エラー: <Mono>{d.error}</Mono></span>);
  if (items.length === 0) return null;
  return <div className="mt-0.5 flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-neutral-600">{items}</div>;
}
