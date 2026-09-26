"use client";

import { useState } from "react";
import { DEFAULT_SUBAGENTS, type Subagent } from "@/lib/api";
import { Button, inputCls } from "./ui";

const ROLE_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/;
const RESERVED = new Set(["pm", "field", "human", "worker", "reputation", "project", "www", "eth"]);

export function subagentsValid(list: Subagent[]): string | null {
  const seen = new Set<string>();
  for (const x of list) {
    if (!ROLE_RE.test(x.role)) return `役割「${x.role || "（空）"}」は英小文字・数字・ハイフン（32 文字まで、先頭と末尾は英数字）にしてください`;
    if (RESERVED.has(x.role) || x.role.startsWith("project-")) return `役割「${x.role}」は予約語なので使えません`;
    if (seen.has(x.role)) return `役割「${x.role}」が重複しています`;
    seen.add(x.role);
    if (!x.name.trim()) return `役割「${x.role}」の名前を入れてください`;
  }
  if (list.length > 12) return "専門エージェントは 12 件までです";
  return null;
}

/** PM Agent 配下の専門 AI エージェント一覧。所有者が追加・削除・編集する。
 *  role は ENS の subname（<role>.<agent>）になり、name / description は record に書く。rules（プロンプト）は ENS に書かず、AI 工程の system prompt に足す */
export function SubagentsEditor({ value, onChange, published = false, defaultOpen = false }: { value: Subagent[]; onChange: (v: Subagent[]) => void; published?: boolean; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const err = subagentsValid(value);
  const upd = (i: number, k: keyof Subagent, v: string) => onChange(value.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const remove = (i: number) => onChange(value.filter((_, j) => j !== i));
  const add = () => onChange([...value, { role: "", name: "", description: "", rules: "" }]);
  const reset = () => onChange(DEFAULT_SUBAGENTS.map((x) => ({ ...x })));
  return (
    <div className="rounded-md border border-neutral-200">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm">
        <span className="font-medium">専門エージェント <span className="ml-1 text-xs font-normal text-neutral-500">{value.length} 件{err && <span className="ml-2 text-neutral-900">要修正</span>}</span></span>
        <span className="text-xs text-neutral-500">{open ? "閉じる" : "開く"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-neutral-200 px-3 py-3">
          <p className="text-xs text-neutral-500">
            PM Agent が案件を分解するときの AI 担当です。役割（role）は ENS の subname（<span className="font-mono">&lt;role&gt;.&lt;agent&gt;</span>）になり、名前と説明は record に書きます。プロンプトは ENS には書かず、その役割の成果物を作るときの system prompt に足します。
            {published && " 公開済みの Agent では、追加・名前や説明の変更は ENS にも反映されます（プラットフォーム公開はワーカーが、Creator 所有は自分のウォレットで署名）。削除は一覧から外れるだけで ENS の subname は残ります。"}
          </p>
          {value.length === 0 && <p className="text-xs text-neutral-700">専門エージェントがありません。すべての AI タスクは role=general として PM Agent 自身が実行します。</p>}
          {value.map((x, i) => (
            <div key={i} className="space-y-2 rounded-md border border-neutral-200 p-3">
              <div className="grid gap-2 sm:grid-cols-[10rem_1fr_auto]">
                <input id={`sub-role-${i}`} className={`${inputCls} font-mono`} placeholder="role（例: designer）" value={x.role} onChange={(e) => upd(i, "role", e.target.value.toLowerCase())} />
                <input id={`sub-name-${i}`} className={inputCls} placeholder="名前（例: Designer Agent）" value={x.name} onChange={(e) => upd(i, "name", e.target.value)} />
                <Button variant="ghost" onClick={() => remove(i)}>削除</Button>
              </div>
              <input id={`sub-desc-${i}`} className={inputCls} placeholder="説明（ENS の description。200 文字まで）" maxLength={200} value={x.description} onChange={(e) => upd(i, "description", e.target.value)} />
              <textarea id={`sub-rules-${i}`} className={inputCls} rows={3} maxLength={4000} placeholder={"この役割の成果物に何を含めるか、技術スタック、形式など（system prompt に追加。ENS には書きません）"} value={x.rules} onChange={(e) => upd(i, "rules", e.target.value)} />
            </div>
          ))}
          {err && <p className="text-xs text-neutral-900">{err}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={add} disabled={value.length >= 12}>＋ 追加</Button>
            <Button variant="ghost" onClick={reset}>既定の 4 つに戻す</Button>
          </div>
        </div>
      )}
    </div>
  );
}
