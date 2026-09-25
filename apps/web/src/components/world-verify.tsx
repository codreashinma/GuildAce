"use client";

import { useState } from "react";
import { IDKitRequestWidget, proofOfHuman, type IDKitResult } from "@worldcoin/idkit";
import { api, type RpContext } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui";

export type WorldAction = "request" | "approve" | "review" | "jury" | "human-task";

/**
 * World ID で人間確認をしてから onVerified(proof) を呼ぶボタン。
 * World 連携がモックのときは proof なしで onVerified(null) を呼ぶ。
 * onVerified は API 呼び出し（検証＋処理）を行い、失敗時は throw する。
 */
export function WorldVerifyButton({ action, signal, label, onVerified, disabled, variant = "primary" }: {
  action: WorldAction; signal: string; label: string; disabled?: boolean; variant?: "primary" | "secondary" | "danger";
  onVerified: (idkitResponse: IDKitResult | null) => Promise<void>;
}) {
  const { config } = useAuth();
  const [open, setOpen] = useState(false);
  const [rp, setRp] = useState<RpContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = async () => {
    setErr(null);
    setBusy(true);
    try {
      if (!config || config.mock.world) {
        await onVerified(null);
        return;
      }
      const ctx = await api<RpContext>(`/world/rp-context?action=${action}`);
      setRp(ctx);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <Button variant={variant} onClick={start} disabled={disabled || busy}>
        <span className="mr-1">◎</span>{busy ? "処理中…" : label}
      </Button>
      {err && <span className="max-w-xs text-xs text-rose-600">{err}</span>}
      {config && !config.mock.world && rp && (
        <IDKitRequestWidget
          open={open}
          onOpenChange={setOpen}
          app_id={config.world_app_id as `app_${string}`}
          action={action}
          rp_context={rp}
          allow_legacy_proofs={true}
          preset={proofOfHuman({ signal })}
          handleVerify={async (result) => {
            await onVerified(result);
          }}
          onSuccess={() => setOpen(false)}
          onError={(code) => setErr(`World ID: ${code}`)}
        />
      )}
    </div>
  );
}
