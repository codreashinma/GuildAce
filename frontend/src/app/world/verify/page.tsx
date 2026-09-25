"use client";

import { useState } from "react";
import {
  IDKitRequestWidget,
  proofOfHuman,
  type RpContext,
} from "@worldcoin/idkit";

type RpContextResponse = RpContext & {
  action: string;
  error?: string;
};

export default function WorldVerifyPage() {
  const appId = process.env.NEXT_PUBLIC_WORLD_APP_ID as
    | `app_${string}`
    | undefined;

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [rpContext, setRpContext] = useState<RpContext | null>(null);
  const [worldAction, setWorldAction] = useState("");
  const [message, setMessage] = useState("確認を開始してください。");

  async function startVerification() {
    if (!appId) {
      setMessage("NEXT_PUBLIC_WORLD_APP_IDが設定されていません。");
      return;
    }

    setLoading(true);
    setMessage("World ID確認の準備中です。");

    try {
      const response = await fetch(
        "/world/rp-context?action=approve&scope=task-123",
        { cache: "no-store" },
      );
      const data = (await response.json()) as RpContextResponse;

      if (!response.ok) {
        throw new Error(
          data.error ?? "RPコンテキストを取得できませんでした。",
        );
      }

      setRpContext({
        rp_id: data.rp_id,
        nonce: data.nonce,
        created_at: data.created_at,
        expires_at: data.expires_at,
        signature: data.signature,
      });
      setWorldAction(data.action);
      setOpen(true);
      setMessage("World IDで確認してください。");
    } catch (error) {
      setMessage(
        error instanceof Error
          ? error.message
          : "確認の準備中にエラーが発生しました。",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-bold">World ID確認</h1>

      <p>同じ人が同じ対象を重複承認しないための確認を行います。</p>

      <button
        type="button"
        onClick={startVerification}
        disabled={loading}
        className="rounded-lg bg-black px-6 py-3 text-white disabled:opacity-50"
      >
        {loading ? "準備中..." : "World IDで確認する"}
      </button>

      <p aria-live="polite">{message}</p>

      {appId && rpContext && worldAction ? (
        <IDKitRequestWidget
          open={open}
          onOpenChange={setOpen}
          app_id={appId}
          action={worldAction}
          rp_context={rpContext}
          allow_legacy_proofs={false}
          preset={proofOfHuman()}
          onSuccess={() => {
            setMessage(
              "World IDの証明を受け取りました。まだPython側の検証前です。",
            );
          }}
          onError={(errorCode) => {
            setMessage(`World ID確認エラー: ${errorCode}`);
          }}
        />
      ) : null}
    </main>
  );
}
