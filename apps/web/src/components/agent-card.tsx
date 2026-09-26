import Link from "next/link";
import { CATEGORY_LABEL, short, type Agent } from "@/lib/api";
import { Badge, Card, Stars } from "./ui";

export function AgentCard({ agent }: { agent: Agent }) {
  return (
    <Link href={`/agents/${agent.id}`} className="block">
      <Card className="h-full transition hover:border-neutral-900">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-lg bg-neutral-900 text-[11px] font-bold tracking-widest text-white">AI</div>
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 items-center gap-2">
              <h3 className="truncate font-semibold">{agent.name}</h3>
              <Badge>{CATEGORY_LABEL[agent.category] ?? agent.category}</Badge>
            </div>
            {agent.ens_name && <div className="truncate font-mono text-xs text-neutral-900">{agent.ens_name}</div>}
            <div className="truncate text-xs text-neutral-500">Creator {agent.creator.display_name ? `${agent.creator.display_name} ` : ""}<span className="font-mono">{short(agent.creator.wallet_address)}</span></div>
          </div>
        </div>
        <p className="mt-3 line-clamp-2 text-sm text-neutral-600">{agent.description || "(No description)"}</p>
        <div className="mt-4 flex items-end justify-between gap-2 text-sm">
          <Stars value={Number(agent.rating_avg)} count={agent.rating_count} />
          <div className="text-right tabular-nums text-neutral-500">
            <div className="whitespace-nowrap">Fee {agent.fee_bps / 100}%</div>
            <div className="whitespace-nowrap">Completed {agent.completed_count}</div>
          </div>
        </div>
      </Card>
    </Link>
  );
}
