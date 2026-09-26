"use client";

import { useState } from "react";
import { SUBAGENT_ROLES } from "@/lib/api";
import { Field, inputCls } from "./ui";

/** 専門 AI エージェント（designer / frontend / backend / qa）ごとの追加プロンプト。PM Agent の所有者が編集する。
 *  AI 工程の実行時に、その role の system prompt に足される。計画時にも担当割り当ての参考として渡す。ENS には書かない */
export function SubagentRulesEditor({ value, onChange, defaultOpen = false }: { value: Record<string, string>; onChange: (v: Record<string, string>) => void; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  const filled = SUBAGENT_ROLES.filter((r) => (value[r.role] ?? "").trim()).length;
  return (
    <div className="rounded-md border border-neutral-200">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm">
        <span className="font-medium">専門エージェントのプロンプト <span className="ml-1 text-xs font-normal text-neutral-500">{filled} / {SUBAGENT_ROLES.length} 件設定</span></span>
        <span className="text-xs text-neutral-500">{open ? "閉じる" : "開く"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-neutral-200 px-3 py-3">
          <p className="text-xs text-neutral-500">PM Agent 配下の専門 AI エージェント（ENS の <span className="font-mono">designer.&lt;agent&gt;</span> など）が成果物を作るときの system prompt に追加されます。空欄の役割は PM の「進め方・ルール」だけで動きます。ENS には書きません。</p>
          {SUBAGENT_ROLES.map((r) => (
            <Field key={r.role} label={r.label} hint={r.hint}>
              <textarea id={`subagent-${r.role}`} className={inputCls} rows={3} value={value[r.role] ?? ""} onChange={(e) => onChange({ ...value, [r.role]: e.target.value })} />
            </Field>
          ))}
        </div>
      )}
    </div>
  );
}
