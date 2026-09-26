"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, short, usdc, type MeSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Amount, Badge, Card, Empty, EnsLink, HumanBadge, Mono, PageTitle, Stars, TxLink } from "@/components/ui";

const KIND: Record<string, string> = { person: "会社の人員", "agent-payout": "Agent の受取先", "company-admin": "会社の管理者" };
const ROLE: Record<string, string> = { pm: "PM 管理費", human: "Human Task", ai: "AI 工程" };

/** A4: マイページ。自分のウォレット・ENS 名・World で人間確認した行為・所属会社・作成した Agent・関わった案件・受取履歴（GET /me/summary） */
export default function MePage() {
  const { me, dev, config } = useAuth();
  const { data: s, error } = useQuery({ queryKey: ["me-summary", me?.id], queryFn: () => api<MeSummary>("/me/summary"), enabled: !!me, refetchInterval: 8000 });
  if (!me) return <p className="text-sm text-neutral-500">Sign in してください。</p>;
  if (error) return <p className="text-sm text-neutral-700">読み込みに失敗しました: {(error as Error).message}</p>;
  if (!s) return <p className="text-sm text-neutral-500">読み込み中…</p>;
  const total = s.cases.as_client + s.cases.as_approver + s.cases.as_worker + s.cases.as_jury;
  return (
    <div className="space-y-6">
      <PageTitle title="マイページ" sub="このウォレットに紐づく名前・行為・所属・受取をまとめて表示します。ENS 名はプラットフォームが Sepolia に発行したもの、World ID の行為は proof を検証して記録したものです。" />

      <Card>
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-lg font-semibold">{s.primary_ens ? <EnsLink name={s.primary_ens.name} /> : s.user.display_name ?? short(s.user.wallet_address)}</h2>
              {s.world_actions.length > 0 && <HumanBadge />}
              {dev && <Badge>デモログイン（鍵なし）</Badge>}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-neutral-500">
              <span className="whitespace-nowrap">ウォレット <Mono className="text-neutral-900">{s.user.wallet_address}</Mono></span>
              {s.user.display_name && <span className="whitespace-nowrap">表示名 {s.user.display_name}</span>}
              <span className="whitespace-nowrap">登録 {new Date(s.user.created_at).toLocaleDateString("ja-JP")}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-6 gap-y-1 text-right text-xs text-neutral-500 sm:grid-cols-4">
            <Stat label="発注" value={s.cases.as_client} /><Stat label="承認者" value={s.cases.as_approver} /><Stat label="Human Task" value={s.cases.as_worker} /><Stat label="Jury 投票" value={s.cases.as_jury} />
          </div>
        </div>
      </Card>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <h2 className="font-semibold">ENS 名 <span className="text-xs font-normal text-neutral-500">{config?.ens_parent_name ?? "guildace.eth"} や会社・Creator の .eth の下に発行された名前</span></h2>
          {s.ens_names.length === 0 ? <p className="mt-3 text-sm text-neutral-500">まだありません。会社の人員として登録されるか、Agent の受取先に自分のアドレスを指定すると名前が付きます。</p> : (
            <ul className="mt-3 space-y-2">
              {s.ens_names.map((n) => (
                <li key={n.name} className="flex flex-wrap items-center gap-2 text-sm">
                  <EnsLink name={n.name} /><Badge status={n.verified ? "published" : undefined}>{KIND[n.kind] ?? n.kind}</Badge>
                  {!n.verified && <span className="text-xs text-neutral-400">(未書込)</span>}
                  {n.tx_hash && <TxLink hash={n.tx_hash} label="tx" />}
                  {n.note && <span className="text-xs text-neutral-500">{n.note}</span>}
                  <Link href={n.link} className="text-xs text-neutral-500 underline underline-offset-2 hover:text-neutral-900">開く</Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="font-semibold">World ID で人間確認した行為 <span className="text-xs font-normal text-neutral-500">行為ごとの回数。nullifier は表示しません</span></h2>
          {s.world_actions.length === 0 ? <p className="mt-3 text-sm text-neutral-500">まだありません。依頼開始・承認・レビュー・Jury 投票・Human Task 受注のいずれかで World 確認を行うと記録されます。</p> : (
            <ul className="mt-3 divide-y divide-neutral-100 text-sm">
              {s.world_actions.map((w) => (
                <li key={w.action} className="flex flex-wrap items-center justify-between gap-2 py-2">
                  <span className="flex items-center gap-2"><HumanBadge />{w.label} <Mono>{w.action}</Mono></span>
                  <span className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{w.count} 回{w.last_at && ` · 最終 ${new Date(w.last_at).toLocaleString("ja-JP")}`}</span>
                </li>
              ))}
            </ul>
          )}
          {s.reviews_received.count > 0 && <p className="mt-3 flex items-center gap-2 text-sm">人としての評価 <Stars value={s.reviews_received.avg ?? 0} count={s.reviews_received.count} /></p>}
        </Card>

        <Card>
          <h2 className="font-semibold">所属会社</h2>
          {s.companies.length === 0 ? <p className="mt-3 text-sm text-neutral-500">所属している会社はありません。<Link href="/companies" className="underline">会社と人員</Link> から登録できます。</p> : (
            <ul className="mt-3 space-y-2 text-sm">
              {s.companies.map((c, i) => (
                <li key={`${c.id}-${i}`} className="flex flex-wrap items-center gap-2">
                  <Link href="/companies" className="font-medium underline-offset-2 hover:underline">{c.name}</Link><EnsLink name={c.ens_name} />
                  <Badge status={c.relation === "admin" ? "published" : undefined}>{c.relation === "admin" ? "管理者" : "人員"}</Badge>
                  {c.member_ens && <span className="text-xs text-neutral-500">として <Mono className="text-neutral-900">{c.member_ens}</Mono></span>}
                  {c.available === false && <span className="text-xs text-neutral-400">稼働不可</span>}
                  {!c.ens_verified && <span className="text-xs text-neutral-400">(所有未確認)</span>}
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <h2 className="font-semibold">作成した PM Agent</h2>
          {s.agents.length === 0 ? <p className="mt-3 text-sm text-neutral-500">まだありません。<Link href="/agents/new" className="underline">新しい PM Agent</Link> を作成できます。</p> : (
            <ul className="mt-3 space-y-2 text-sm">
              {s.agents.map((a) => (
                <li key={a.id} className="flex flex-wrap items-center gap-2">
                  <Link href={`/agents/${a.id}`} className="font-medium underline-offset-2 hover:underline">{a.name}</Link><Badge status={a.status} />
                  {a.ens_name && <EnsLink name={a.ens_name} />}{a.owner_mode === "creator" && <Badge>Creator 所有</Badge>}
                  <span className="whitespace-nowrap text-xs tabular-nums text-neutral-500">★{Number(a.rating_avg).toFixed(1)} ({a.rating_count}) · 実績 {a.completed_count}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">受取履歴 <span className="text-xs font-normal text-neutral-500">Escrow が自分のアドレスへ支払った工程（PM 管理費・Human Task・AI 工程の受取先）</span></h2>
          <div className="whitespace-nowrap text-sm">合計 <Amount value={usdc(s.earnings_total)} /></div>
        </div>
        {s.earnings.length === 0 ? <div className="mt-3"><Empty>まだ受け取りはありません{total === 0 && "。案件に関わると、ここに支払いが並びます"}</Empty></div> : (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="whitespace-nowrap text-left text-xs text-neutral-500"><tr><th className="py-1 pr-3">日時</th><th className="pr-3">案件</th><th className="pr-3">工程</th><th className="pr-3">種別</th><th className="pr-3 text-right">金額</th><th className="pr-3">状態</th><th>tx</th></tr></thead>
              <tbody>
                {s.earnings.map((e) => (
                  <tr key={e.task_id} className="border-t border-neutral-100 [&>td]:py-2 [&>td]:pr-3">
                    <td className="whitespace-nowrap text-xs tabular-nums text-neutral-500">{e.at ? new Date(e.at).toLocaleString("ja-JP") : "—"}</td>
                    <td className="min-w-40"><Link href={`/cases/${e.case_id}`} className="underline-offset-2 hover:underline">{e.case_title}</Link></td>
                    <td className="min-w-32">{e.task_title}</td>
                    <td><Badge>{ROLE[e.role] ?? e.role}</Badge></td>
                    <td className="whitespace-nowrap text-right tabular-nums">{usdc(e.amount)}</td>
                    <td><Badge status={`chain:${e.chain_status}`} /></td>
                    <td><TxLink hash={e.tx_hash} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="mt-3 text-xs text-neutral-500">裁定済（resolved）は Jury の判断で解放または返金された工程です。金額は Escrow に預託された工程の額で、合計には支払済のみを含めます。</p>
      </Card>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div><div className="text-lg font-semibold tabular-nums text-neutral-900">{value}</div><div className="whitespace-nowrap">{label}</div></div>;
}
