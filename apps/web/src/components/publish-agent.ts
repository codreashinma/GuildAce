"use client";

import { useState } from "react";
import { usePublicClient, useSendTransaction } from "wagmi";
import { api, type Agent } from "@/lib/api";
import { useEnsureSepolia } from "@/lib/chain";

type PublishResult = { mode: "platform" | "creator"; mock?: boolean; txs?: { to: string; data: string; label: string }[]; ens_name?: string; agent: Agent };

/** D1: Agent の公開。platform はワーカーが発行、creator は Creator のウォレットで register / multicall に署名する */
export function usePublishAgent() {
  const { sendTransactionAsync } = useSendTransaction();
  const ensureSepolia = useEnsureSepolia();
  const pc = usePublicClient();
  const [step, setStep] = useState<string | null>(null);
  const publish = async (agentId: string): Promise<Agent> => {
    setStep("公開を開始…");
    try {
      const r = await api<PublishResult>(`/agents/${agentId}/publish`, { method: "POST" });
      if (r.mode !== "creator" || r.mock || !r.txs?.length) return r.agent;
      await ensureSepolia();
      let last = "";
      for (const tx of r.txs) {
        setStep(`${tx.label} に署名…`);
        const h = await sendTransactionAsync({ to: tx.to as `0x${string}`, data: tx.data as `0x${string}` });
        setStep("トランザクション確認中…");
        await pc!.waitForTransactionReceipt({ hash: h });
        last = h;
      }
      return await api<Agent>(`/agents/${agentId}/ens-written`, { method: "POST", json: { tx_hash: last } });
    } finally {
      setStep(null);
    }
  };
  return { publish, step };
}
