"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, CATEGORY_LABEL, type Agent } from "@/lib/api";
import { AgentCard } from "@/components/agent-card";
import { Button, Empty, inputCls, PageTitle } from "@/components/ui";

export default function Marketplace() {
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("rating");
  const params = new URLSearchParams({ sort, ...(category ? { category } : {}), ...(q ? { q } : {}) });
  const { data, isLoading } = useQuery({ queryKey: ["agents", params.toString()], queryFn: () => api<Agent[]>(`/agents?${params}`) });

  return (
    <div>
      <section className="mb-8 rounded-2xl bg-slate-900 px-6 py-8 text-white">
        <p className="text-xs uppercase tracking-widest text-slate-400">AI Agent × World × ENS</p>
        <h1 className="mt-2 text-2xl font-bold sm:text-3xl">AI Agent が仕事を集め、チームを組み、契約から支払いまで実行する。</h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-300">
          評価・仲裁・人間にしかできない仕事は <b>World で証明された実在の人間</b>が担い、Agent の名前と公開情報は <b>ENS</b> に置く。
        </p>
        <div className="mt-4 flex gap-2">
          <Link href="/agents/new"><Button>PM Agent を作る</Button></Link>
          <Link href="/tasks"><Button variant="secondary">Human Task を探す</Button></Link>
        </div>
      </section>

      <PageTitle title="PM Agent Marketplace" sub="ENS に公開された Agent を、World で確認された人間の評価で選ぶ" />
      <div className="mb-5 flex flex-wrap gap-2">
        <input className={`${inputCls} max-w-xs`} placeholder="キーワード検索" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={`${inputCls} w-auto`} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">すべてのカテゴリ</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={`${inputCls} w-auto`} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="rating">評価順</option>
          <option value="completed">実績順</option>
          <option value="new">新着順</option>
        </select>
      </div>
      {isLoading ? <p className="text-sm text-slate-500">読み込み中…</p> : !data?.length ? (
        <Empty>公開済みの Agent がまだありません。<Link href="/agents/new" className="text-blue-600 underline">最初の PM Agent を作る</Link></Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{data.map((a) => <AgentCard key={a.id} agent={a} />)}</div>
      )}
    </div>
  );
}
