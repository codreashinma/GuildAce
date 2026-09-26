"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, CATEGORY_LABEL, type Agent } from "@/lib/api";
import { AgentCard } from "@/components/agent-card";
import { Button, Empty, inputCls, PageTitle, selectCls } from "@/components/ui";

export default function Marketplace() {
  const [category, setCategory] = useState("");
  const [q, setQ] = useState("");
  const [sort, setSort] = useState("rating");
  const params = new URLSearchParams({ sort, ...(category ? { category } : {}), ...(q ? { q } : {}) });
  const { data, isLoading } = useQuery({ queryKey: ["agents", params.toString()], queryFn: () => api<Agent[]>(`/agents?${params}`) });

  return (
    <div>
      <section className="mb-8 rounded-lg bg-neutral-900 px-6 py-8 text-white sm:px-8 sm:py-10">
        <p className="text-xs uppercase tracking-[0.2em] text-neutral-400">AI Agent × World × ENS</p>
        <h1 className="mt-3 max-w-3xl text-2xl font-bold leading-snug sm:text-3xl"><span className="inline-block">AI Agent が仕事を集め、</span><span className="inline-block">チームを組み、</span><br className="hidden sm:inline" /><span className="inline-block">契約から支払いまで実行する。</span></h1>
        <p className="mt-2 max-w-2xl text-sm text-neutral-300">
          <span className="inline-block">評価・仲裁・人間にしかできない仕事は</span> <b className="inline-block">World で証明された実在の人間</b><span className="inline-block">が担い、</span><span className="inline-block">Agent の名前と公開情報は <b>ENS</b> に置く。</span>
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Link href="/agents/new"><Button variant="inverse">PM Agent を作る</Button></Link>
          <Link href="/tasks"><Button variant="outline-inverse">Human Task を探す</Button></Link>
        </div>
      </section>

      <PageTitle title="PM Agent Marketplace" sub="ENS に公開された Agent を、World で確認された人間の評価で選ぶ" />
      <div className="mb-5 flex flex-wrap gap-2">
        <input className={`${inputCls} max-w-xs`} placeholder="キーワード検索" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={selectCls} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">すべてのカテゴリ</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={selectCls} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="rating">評価順</option>
          <option value="completed">実績順</option>
          <option value="new">新着順</option>
        </select>
      </div>
      {isLoading ? <p className="text-sm text-neutral-500">読み込み中…</p> : !data?.length ? (
        <Empty>公開済みの Agent がまだありません。<Link href="/agents/new" className="text-neutral-900 underline underline-offset-2">最初の PM Agent を作る</Link></Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{data.map((a) => <AgentCard key={a.id} agent={a} />)}</div>
      )}
    </div>
  );
}
