"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";
import { api, CATEGORY_LABEL, type Agent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Field, inputCls, PageTitle } from "@/components/ui";
import { usePublishAgent } from "@/components/publish-agent";
import { EnsNameCheck } from "@/components/ens-records";

export default function NewAgent() {
  const router = useRouter();
  const { me, config } = useAuth();
  const [f, setF] = useState({ name: "Web開発 PM Agent", label: "", description: "", category: "web", rules: "", fee_bps: 200, payout_address: "" });
  const [mode, setMode] = useState<"platform" | "creator">("platform");
  const [ownName, setOwnName] = useState("");
  const [ownOk, setOwnOk] = useState<{ ok: boolean; checking: boolean }>({ ok: false, checking: false });
  const onOwnStatus = useCallback((s: { ok: boolean; checking: boolean }) => setOwnOk(s), []);
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const { publish: doPublish, step } = usePublishAgent();
  const set = (k: string, v: string | number) => setF((s) => ({ ...s, [k]: v }));

  const submit = async (publish: boolean) => {
    setErr(null);
    setBusy(true);
    try {
      const a = await api<Agent>("/agents", { method: "POST", json: { ...f, payout_address: f.payout_address || null, parent_ens_name: mode === "creator" ? ownName : null } });
      if (publish) await doPublish(a.id);
      router.push(`/agents/${a.id}`);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (!me) return <p className="text-sm text-neutral-500">ウォレットを接続して Sign in してください。</p>;
  const parent = mode === "creator" ? (ownName || "<your-name>.eth") : (config?.ens_parent_name ?? "choice.eth");
  const ens = `${f.label || "<label>"}.${parent}`;

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="PM Agent を作成" sub="作成した Agent は ENS の subname として公開され、利用されるたびに利用料が入ります" />
      <Card className="space-y-4">
        <Field label="名前"><input className={inputCls} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
        <Field label="公開先（ENS の親名）" hint="Creator 自身の .eth の下に置くと、名前の所有者は Creator になり、発行と record 書き込みは自分のウォレットで署名します">
          <div className="grid gap-2 sm:grid-cols-2">
            <button type="button" onClick={() => setMode("platform")} className={`rounded-md border p-3 text-left text-sm ${mode === "platform" ? "border-neutral-900 shadow-[2px_2px_0_0_#171717]" : "border-neutral-300"}`}>
              <div className="font-medium">プラットフォームの親名</div><div className="mt-0.5 font-mono text-xs text-neutral-600">&lt;label&gt;.{config?.ens_parent_name ?? "choice.eth"}</div><div className="mt-1 text-xs text-neutral-500">ウォレット署名不要。運用ウォレットが発行</div>
            </button>
            <button type="button" onClick={() => setMode("creator")} className={`rounded-md border p-3 text-left text-sm ${mode === "creator" ? "border-neutral-900 shadow-[2px_2px_0_0_#171717]" : "border-neutral-300"}`}>
              <div className="font-medium">自分の ENS 名の下</div><div className="mt-0.5 font-mono text-xs text-neutral-600">&lt;label&gt;.&lt;your-name&gt;.eth</div><div className="mt-1 text-xs text-neutral-500">所有者を ENSv2 で確認。2 本の tx に署名</div>
            </button>
          </div>
          {mode === "creator" && (
            <>
              <input className={`${inputCls} mt-2`} placeholder="nakamine.eth（Sepolia ENSv2 で所有している名前）" value={ownName} onChange={(e) => setOwnName(e.target.value.toLowerCase())} />
              <EnsNameCheck name={ownName} onStatus={onOwnStatus} />
            </>
          )}
        </Field>
        <Field label="ENS ラベル" hint={`公開先: ${ens}（英小文字・数字・ハイフン）`}>
          <input className={inputCls} placeholder="web-pm" value={f.label} onChange={(e) => set("label", e.target.value.toLowerCase())} />
        </Field>
        <Field label="説明"><textarea className={inputCls} rows={3} value={f.description} onChange={(e) => set("description", e.target.value)} /></Field>
        <div className="grid grid-cols-2 gap-4">
          <Field label="カテゴリ">
            <select className={inputCls} value={f.category} onChange={(e) => set("category", e.target.value)}>
              {Object.entries(CATEGORY_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
          <Field label="利用料（%）">
            <input className={inputCls} type="number" min={0} max={50} step={0.5} value={f.fee_bps / 100} onChange={(e) => set("fee_bps", Math.round(Number(e.target.value) * 100))} />
          </Field>
        </div>
        <Field label="進め方・ルール" hint="PM Agent の system prompt になります。タスクの切り方、人間に任せる仕事、成果物の形式など">
          <textarea className={inputCls} rows={5} placeholder={"1. 案件を 4〜6 タスクに分解する\n2. 現地確認や実物レビューは Human Task にする\n3. 成果物は Markdown で書く"} value={f.rules} onChange={(e) => set("rules", e.target.value)} />
        </Field>
        <Field label="受取アドレス" hint="空なら自分のウォレット。ENS の addr レコードにも登録されます">
          <input className={inputCls} placeholder={me.wallet_address} value={f.payout_address} onChange={(e) => set("payout_address", e.target.value)} />
        </Field>
        <ErrorBox error={err} />
        <div className="flex justify-end gap-2">
          <Button variant="secondary" disabled={busy || !f.label} onClick={() => submit(false)}>下書き保存</Button>
          <Button disabled={busy || !f.label || (mode === "creator" && (!/^[a-z0-9-]+\.eth$/.test(ownName) || !ownOk.ok))} onClick={() => submit(true)}>{step ?? (busy ? "処理中…" : "ENS に公開する")}</Button>
        </div>
      </Card>
    </div>
  );
}
