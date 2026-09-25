"use client";

import { useState } from "react";
import { useSignTypedData } from "wagmi";
import { api, type TypedData } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { WorldVerifyButton } from "./world-verify";
import { ErrorBox } from "./ui";

/** UC-005 / FR-010 / FR-011: 承認者が World で人間確認し、(成果物ハッシュ, 支払先) に EIP-712 で署名する */
export function ApproveButton({ caseId, taskId, deliverableHash, approvalCount, threshold, alreadyApproved, onDone }: {
  caseId: string; taskId: string; deliverableHash: string | null; approvalCount: number; threshold: number; alreadyApproved: boolean; onDone: () => void;
}) {
  const { me } = useAuth();
  const { signTypedDataAsync } = useSignTypedData();
  const [err, setErr] = useState<unknown>(null);
  if (!me) return null;
  if (alreadyApproved) return <span className="whitespace-nowrap text-xs text-neutral-900">承認済み（{approvalCount}/{threshold}）</span>;
  return (
    <div className="flex flex-col gap-1">
      <WorldVerifyButton action="approve" signal={`${taskId}:${deliverableHash}`} label={`World で人間確認して承認（${approvalCount}/${threshold}）`}
        onVerified={async (proof) => {
          setErr(null);
          try {
            const typed = await api<TypedData>(`/cases/${caseId}/tasks/${taskId}/typed-data`);
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
