"use client";

import { useState } from "react";
import { DEFAULT_SUBAGENTS, type Subagent } from "@/lib/api";
import { Button, inputCls } from "./ui";

const ROLE_RE = /^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$/;
const RESERVED = new Set(["pm", "field", "human", "worker", "reputation", "project", "www", "eth"]);

export function subagentsValid(list: Subagent[]): string | null {
  const seen = new Set<string>();
  for (const x of list) {
    if (!ROLE_RE.test(x.role)) return `ENS label "${x.role || "(empty)"}" must use lowercase letters, digits and hyphens (up to 32 chars, starting and ending with a letter or digit)`;
    if (RESERVED.has(x.role) || x.role.startsWith("project-")) return `ENS label "${x.role}" is reserved and cannot be used`;
    if (seen.has(x.role)) return `ENS label "${x.role}" is duplicated`;
    seen.add(x.role);
    if (!x.name.trim()) return `Enter a name for "${x.role}"`;
  }
  if (list.length > 12) return "Up to 12 specialist agents are allowed";
  return null;
}

/** PM Agent 配下の専門 AI エージェント一覧。所有者が追加・削除・編集する。
 *  role は ENS の subname（<role>.<agent>）になり、name / description は record に書く。rules（プロンプト）は ENS に書かず、AI 工程の system prompt に足す */
export function SubagentsEditor({ value, onChange, published = false, defaultOpen = false, agentEns }: { value: Subagent[]; onChange: (v: Subagent[]) => void; published?: boolean; defaultOpen?: boolean; agentEns?: string }) {
  const [open, setOpen] = useState(defaultOpen);
  const err = subagentsValid(value);
  const upd = (i: number, k: keyof Subagent, v: string) => onChange(value.map((x, j) => (j === i ? { ...x, [k]: v } : x)));
  const remove = (i: number) => onChange(value.filter((_, j) => j !== i));
  const add = () => onChange([...value, { role: "", name: "", description: "", rules: "" }]);
  const reset = () => onChange(DEFAULT_SUBAGENTS.map((x) => ({ ...x })));
  return (
    <div className="rounded-md border border-neutral-200">
      <button type="button" onClick={() => setOpen((o) => !o)} className="flex w-full items-center justify-between px-3 py-2 text-left text-sm">
        <span className="font-medium">Specialist agents <span className="ml-1 text-xs font-normal text-neutral-500">{value.length}{err && <span className="ml-2 text-neutral-900">Needs fixing</span>}</span></span>
        <span className="text-xs text-neutral-500">{open ? "Close" : "Open"}</span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-neutral-200 px-3 py-3">
          <p className="text-xs text-neutral-500">
            AI workers the PM Agent assigns to when it breaks down a Case. The &quot;ENS label&quot; becomes the start of the subname (<span className="font-mono">&lt;label&gt;.{agentEns ?? "<PM Agent label>.guildace.eth"}</span>) and is issued together with the PM Agent when it is published. The name and description are written as Records; the prompt is not written to ENS and is appended to that Role&apos;s system prompt.
            {published && " For a published Agent, additions and name/description changes are also reflected on ENS (written by the worker for platform-published Agents; signed with your Wallet for Creator-owned ones). Deleting only removes it from the list; the ENS subname remains."}
          </p>
          {value.length === 0 && <p className="text-xs text-neutral-700">No specialist agents. The PM Agent runs every AI Task itself as role=general.</p>}
          {value.map((x, i) => (
            <div key={i} className="space-y-2 rounded-md border border-neutral-200 p-3">
              <div className="grid items-center gap-2 sm:grid-cols-[12rem_1fr_auto]">
                <input id={`sub-role-${i}`} className={`${inputCls} font-mono`} placeholder="e.g. designer" value={x.role} onChange={(e) => upd(i, "role", e.target.value.toLowerCase())} />
                <input id={`sub-name-${i}`} className={inputCls} placeholder="e.g. Designer Agent" value={x.name} onChange={(e) => upd(i, "name", e.target.value)} />
                <Button variant="ghost" onClick={() => remove(i)}>Delete</Button>
              </div>
              <div className="truncate font-mono text-[11px] text-neutral-500" title={`${x.role || "<label>"}.${agentEns ?? "<PM Agent label>.guildace.eth"}`}>ENS: {x.role || "<label>"}.{agentEns ?? "<PM Agent label>.guildace.eth"}</div>
              <input id={`sub-desc-${i}`} className={inputCls} placeholder="Description (ENS description, up to 200 chars)" maxLength={200} value={x.description} onChange={(e) => upd(i, "description", e.target.value)} />
              <textarea id={`sub-rules-${i}`} className={inputCls} rows={3} maxLength={4000} placeholder={"What this Role's Deliverable should include, tech stack, format, etc. (appended to the system prompt; not written to ENS)"} value={x.rules} onChange={(e) => upd(i, "rules", e.target.value)} />
            </div>
          ))}
          {err && <p className="text-xs text-neutral-900">{err}</p>}
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={add} disabled={value.length >= 12}>+ Add</Button>
            <Button variant="ghost" onClick={reset}>Reset to the 4 defaults</Button>
          </div>
        </div>
      )}
    </div>
  );
}
