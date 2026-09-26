"use client";

import { useState } from "react";
import { CredentialRequest, IDKitSessionWidget, type IDKitResultSession } from "@worldcoin/idkit";
import { api, type WorldContext } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button } from "./ui";

export type WorldAction = "request" | "approve" | "review" | "jury" | "human-task";

const ACTION_DESCRIPTION: Record<WorldAction, string> = {
  request: "依頼の開始", approve: "成果物の承認", review: "レビューの投稿", jury: "Jury 投票", "human-task": "Human Task の受注",
};

/**
 * World ID で人間確認をしてから onVerified(proof) を呼ぶボタン。
 *
 * World ID 4.0 の session proof を使う。uniqueness proof（action 付き）は 1 人 1 action 1 回で World App が 2 回目を拒否するため、
 * 初回は createSession（API が session_id を保存）、2 回目以降は保存済み session_id の proveSession で確認する。
 * どの操作向けの proof かは signal（案件 ID など）で束縛し、API が signal_hash を照合する。
 *
 * World 連携がモックのときは proof なしで onVerified(null) を呼ぶ。
 * onVerified は API 呼び出し（検証＋処理）を行い、失敗時は throw する。
 */
export function WorldVerifyButton({ action, signal, label, onVerified, disabled, variant = "primary" }: {
  action: WorldAction; signal: string; label: string; disabled?: boolean; variant?: "primary" | "secondary" | "danger";
  onVerified: (idkitResponse: IDKitResultSession | null) => Promise<void>;
}) {
  const { config } = useAuth();
  const [open, setOpen] = useState(false);
  const [ctx, setCtx] = useState<WorldContext | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const start = async () => {
    setErr(null);
    setBusy(true);
    try {
      if (!config) throw new Error("設定を読み込み中です。少し待ってから再試行してください");
      if (config.mock.world) {
        await onVerified(null);  // World 未設定: proof なし（サーバーはウォレット単位の疑似 session を記録）
        return;
      }
      const c = await api<WorldContext>(`/world/rp-context?action=${action}&signal=${encodeURIComponent(signal)}`);
      setCtx(c);
      setOpen(true);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="inline-flex flex-col gap-1">
      <Button variant={variant} onClick={start} disabled={disabled || busy || !config} title={config?.mock.world ? "World 未設定のため人間確認はモック（proof なし）" : undefined}>
        <span aria-hidden>◎</span><span>{busy ? "処理中…" : config?.mock.world ? `${label}（World モック）` : label}</span>
      </Button>
      {err && <span className="max-w-xs text-xs text-neutral-900">{err}</span>}
      {config && !config.mock.world && ctx && (
        <IDKitSessionWidget
          key={ctx.rp_context.nonce}
          open={open}
          onOpenChange={setOpen}
          app_id={config.world_app_id as `app_${string}`}
          rp_context={ctx.rp_context}
          existing_session_id={ctx.session_id ?? undefined}
          action_description={ACTION_DESCRIPTION[action]}
          constraints={CredentialRequest("proof_of_human", { signal })}
          handleVerify={async (result) => {
            await onVerified(result);
          }}
          onSuccess={() => setOpen(false)}
          onError={(code, report) => {
            console.error("World ID session error", code, report);  // 原因調査用（request_id / bridge の状態が入る）
            setErr(`World ID: ${code}`);
          }}
        />
      )}
    </div>
  );
}
