"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, CATEGORY_LABEL, type Agent } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { Button, Card, ErrorBox, Field, inputCls, PageTitle } from "@/components/ui";

export default function NewAgent() {
  const router = useRouter();
  const { me, config } = useAuth();
  const [f, setF] = useState({ name: "Web開発 PM Agent", label: "", description: "", category: "web", rules: "", fee_bps: 200, payout_address: "" });
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: string, v: string | number) => setF((s) => ({ ...s, [k]: v }));

  const submit = async (publish: boolean) => {
    setErr(null);
    setBusy(true);
    try {
      const a = await api<Agent>("/agents", { method: "POST", json: { ...f, payout_address: f.payout_address || null } });
      if (publish) await api(`/agents/${a.id}/publish`, { method: "POST" });
      router.push(`/agents/${a.id}`);
    } catch (e) {
      setErr(e);
    } finally {
      setBusy(false);
    }
  };

  if (!me) return <p className="text-sm text-neutral-500">ウォレットを接続して Sign in してください。</p>;
  const ens = `${f.label || "<label>"}.${config?.ens_parent_name ?? "choice.eth"}`;

  return (
    <div className="mx-auto max-w-2xl">
      <PageTitle title="PM Agent を作成" sub="作成した Agent は ENS の subname として公開され、利用されるたびに利用料が入ります" />
      <Card className="space-y-4">
        <Field label="名前"><input className={inputCls} value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
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
          <Button disabled={busy || !f.label} onClick={() => submit(true)}>{busy ? "処理中…" : "ENS に公開する"}</Button>
        </div>
      </Card>
    </div>
  );
}
