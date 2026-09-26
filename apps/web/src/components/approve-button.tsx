"use client";

import { useState } from "react";
import { useSignTypedData } from "wagmi";
import { api, type TypedData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { useEnsureSepolia } from "@/lib/chain";
import { WorldVerifyButton } from "./world-verify";
import { ErrorBox } from "./ui";

/** UC-005 / FR-010 / FR-011: 承認者が World で人間確認し、(成果物ハッシュ, 支払先) に EIP-712 で署名する */
export function ApproveButton({ caseId, taskId, deliverableHash, approvalCount, threshold, alreadyApproved, onDone }: {
  caseId: string; taskId: string; deliverableHash: string | null; approvalCount: number; threshold: number; alreadyApproved: boolean; onDone: () => void;
}) {
  const { me, dev, config } = useAuth();
  const { signTypedDataAsync } = useSignTypedData();
  const ensureSepolia = useEnsureSepolia();
  const [err, setErr] = useState<unknown>(null);
  if (!me) return null;
  if (dev) return <span className="max-w-xs text-xs text-neutral-700">デモログイン中は承認できません（EIP-712 署名にはウォレットが必要です）。承認者のウォレットで Sign in してください。</span>;
  if (alreadyApproved) return <span className="whitespace-nowrap text-xs text-neutral-900">承認済み（{approvalCount}/{threshold}）</span>;
  return (
    <div className="flex flex-col gap-1">
      <WorldVerifyButton action="approve" signal={`${taskId}:${deliverableHash}`} label={`World で人間確認して承認（${approvalCount}/${threshold}）`}
        onVerified={async (proof) => {
          setErr(null);
          try {
            const typed = await api<TypedData>(`/cases/${caseId}/tasks/${taskId}/typed-data`);
            if (!config?.mock.chain) await ensureSepolia();
            const signature = await signTypedDataAsync({
              domain: typed.domain as { name: string; version: string; chainId: number; verifyingContract: `0x${string}` },
              types: { Approval: typed.types.Approval }, primaryType: "Approval",
              message: typed.message as { caseId: `0x${string}`; taskId: `0x${string}`; deliverableHash: `0x${string}`; payee: `0x${string}` },
            });
            await api(`/cases/${caseId}/tasks/${taskId}/approve`, { method: "POST", json: { signature, idkit_response: proof } });
            onDone();
          } catch (e) { setErr(e); throw e; }
        }} />
      <ErrorBox error={err} />
    </div>
  );
}
