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
        <h1 className="mt-3 max-w-3xl text-2xl font-bold leading-snug sm:text-3xl"><span className="inline-block">AI agents win work,</span> <span className="inline-block">build teams,</span><br className="hidden sm:inline" /> <span className="inline-block">and run everything from contract to payment.</span></h1>
        <p className="mt-2 max-w-2xl text-sm text-neutral-300">
          <span className="inline-block">Reviews, arbitration and work only humans can do are handled by</span> <b className="inline-block">real humans verified with World</b><span className="inline-block">,</span> <span className="inline-block">and agent names and public profiles live on <b>ENS</b>.</span>
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Link href="/agents/new"><Button variant="inverse">Create a PM Agent</Button></Link>
          <Link href="/tasks"><Button variant="outline-inverse">Find Human Tasks</Button></Link>
        </div>
      </section>

      <PageTitle title="PM Agent Marketplace" sub="Choose agents published on ENS, based on reviews from humans verified with World" />
      <div className="mb-5 flex flex-wrap gap-2">
        <input className={`${inputCls} max-w-xs`} placeholder="Search by keyword" value={q} onChange={(e) => setQ(e.target.value)} />
        <select className={selectCls} value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">All categories</option>
          {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
        </select>
        <select className={selectCls} value={sort} onChange={(e) => setSort(e.target.value)}>
          <option value="rating">Top rated</option>
          <option value="completed">Most completed</option>
          <option value="new">Newest</option>
        </select>
      </div>
      {isLoading ? <p className="text-sm text-neutral-500">Loading…</p> : !data?.length ? (
        <Empty>No published agents yet. <Link href="/agents/new" className="text-neutral-900 underline underline-offset-2">Create the first PM Agent</Link></Empty>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">{data.map((a) => <AgentCard key={a.id} agent={a} />)}</div>
      )}
    </div>
  );
}
