import Link from "next/link";
import { CATEGORY_LABEL, type Agent } from "@/lib/api";
import { Badge, Card, Stars } from "./ui";

export function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link href={`/agents/${agent.id}`} className="block transition hover:-translate-y-0.5">
      <Card className="h-full">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-blue-500 to-indigo-600 text-xl text-white">🤖</div>
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <h3 className="truncate font-semibold">{agent.name}</h3>
              <Badge>{CATEGORY_LABEL[agent.category] ?? agent.category}</Badge>
            </div>
            {agent.ens_name && <div className="truncate font-mono text-xs text-blue-700">{agent.ens_name}</div>}
          </div>
        </div>
        <p className="mt-3 line-clamp-2 text-sm text-slate-600">{agent.description || "（説明なし）"}</p>
        <div className="mt-4 flex items-center justify-between text-sm">
          <Stars value={Number(agent.rating_avg)} count={agent.rating_count} />
          <span className="text-slate-500">Fee {agent.fee_bps / 100}% · Completed {agent.completed_count}</span>
        </div>
      </Card>
    </Link>
  );
}
