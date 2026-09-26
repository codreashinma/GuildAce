"use client";

import { ApiError, type HumanRole, type Policy } from "@/lib/api";
import { Button, Field, inputCls, selectCls } from "@/components/ui";

/** WP-009 の既定（apps/api/app/agents/policy.py の DEFAULT_PHASES と同じ。DEC-002）。作成画面の初期値にだけ使う */
export const DEFAULT_PHASES = [
  { key: "designer", title: "Design" },
  { key: "frontend", title: "Frontend implementation" },
  { key: "backend", title: "Backend implementation" },
  { key: "field", title: "On-site work" },
  { key: "qa", title: "Test & deploy" },
];

export const defaultPolicy = (category: string): Policy => ({
  version: 1, domain: category, workflow: { phases: DEFAULT_PHASES.map((p) => ({ ...p })) }, human_roles: [],
});

/** 編集中の値。min_count は既定値を画面で補わない（Q-007）ため、未入力を null で持つ */
export type PolicyDraft = Omit<Policy, "human_roles"> & { human_roles: (Omit<HumanRole, "min_count"> & { min_count: number | null })[] };

const ROLE_LABEL: Record<HumanRole["role"], string> = { approver: "Approver", reviewer: "Reviewer", juror: "Jury" };

/** API の 422（pydantic の検証エラー）から policy の項目のものを取り出す。キーは "workflow.phases.1.key" の形 */
export function policyErrors(e: unknown): Record<string, string> {
  if (!(e instanceof ApiError) || e.status !== 422) return {};
  try {
    const detail = JSON.parse(e.message) as { loc?: (string | number)[]; msg?: string }[];
    const out: Record<string, string> = {};
    for (const d of Array.isArray(detail) ? detail : []) {
      const loc = d.loc ?? [];
      const i = loc.indexOf("policy");
      if (loc[0] !== "body" || i < 0) continue;
      const path = loc.slice(i + 1).join(".");
      out[path] = [out[path], d.msg ?? ""].filter(Boolean).join(" / ");
    }
    return out;
  } catch {
    return {};
  }
}

function Err({ errors, path }: { errors: Record<string, string>; path: string }) {
  return errors[path] ? <p className="mt-1 text-xs font-medium text-neutral-900">⚠ {errors[path]}</p> : null;
}

/** GRD-006: policy で変えられるのは工程（workflow.phases）と人間の使い方（human_roles）だけ。ツール・上限・World 検証はここでは変えられない */
export function PolicyEditor({ value, onChange, errors = {} }: { value: PolicyDraft; onChange: (v: PolicyDraft) => void; errors?: Record<string, string> }) {
  const phases = value.workflow.phases;
  const setPhases = (next: typeof phases) => onChange({ ...value, workflow: { phases: next } });
  const setPhase = (i: number, k: "key" | "title", v: string) => setPhases(phases.map((p, j) => (j === i ? { ...p, [k]: v } : p)));
  const move = (i: number, d: -1 | 1) => {
    const next = [...phases];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setPhases(next);
  };
  const roles = value.human_roles;
  const setRoles = (next: typeof roles) => onChange({ ...value, human_roles: next });
  const setRole = (i: number, patch: Partial<(typeof roles)[number]>) => setRoles(roles.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  return (
    <div className="space-y-4">
      <Field label="Steps (template for Task breakdown)" hint="Keys use lowercase letters, digits and hyphens (used for the Step's ENS subname). 1-20 Steps, keys must be unique">
        <div className="space-y-2">
          {phases.map((p, i) => (
            <div key={i}>
              <div className="flex items-center gap-2">
                <span className="w-5 text-right text-xs text-neutral-500">{i + 1}</span>
                <input className={`${inputCls} w-36 font-mono`} placeholder="key" value={p.key} onChange={(e) => setPhase(i, "key", e.target.value.toLowerCase())} />
                <input className={inputCls} placeholder="Display name" value={p.title} maxLength={80} onChange={(e) => setPhase(i, "title", e.target.value)} />
                <Button type="button" variant="ghost" className="px-2" disabled={i === 0} onClick={() => move(i, -1)} aria-label="Move up">↑</Button>
                <Button type="button" variant="ghost" className="px-2" disabled={i === phases.length - 1} onClick={() => move(i, 1)} aria-label="Move down">↓</Button>
                <Button type="button" variant="ghost" className="px-2" disabled={phases.length <= 1} onClick={() => setPhases(phases.filter((_, j) => j !== i))} aria-label="Delete">×</Button>
              </div>
              <Err errors={errors} path={`workflow.phases.${i}.key`} />
              <Err errors={errors} path={`workflow.phases.${i}.title`} />
            </div>
          ))}
          <Err errors={errors} path="workflow.phases" />
          <Err errors={errors} path="workflow" />
          <Button type="button" variant="secondary" disabled={phases.length >= 20} onClick={() => setPhases([...phases, { key: "", title: "" }])}>Add Step</Button>
        </div>
      </Field>
      <Field label="Human usage" hint="For each Role, choose whether World proof is required and the minimum count. The minimum count is required">
        <div className="space-y-2">
          {roles.length === 0 && <p className="text-xs text-neutral-500">None specified</p>}
          {roles.map((r, i) => (
            <div key={i}>
              <div className="flex flex-wrap items-center gap-3">
                <select className={selectCls} value={r.role} onChange={(e) => setRole(i, { role: e.target.value as HumanRole["role"] })}>
                  {Object.entries(ROLE_LABEL).map(([k, v]) => <option key={k} value={k}>{v} ({k})</option>)}
                </select>
                <label className="inline-flex items-center gap-1 text-sm"><input type="checkbox" checked={r.world_verified} onChange={(e) => setRole(i, { world_verified: e.target.checked })} />Require World proof</label>
                <label className="inline-flex items-center gap-1 text-sm">Minimum count
                  <input className={`${inputCls} w-20`} type="number" min={1} value={r.min_count ?? ""} onChange={(e) => setRole(i, { min_count: e.target.value === "" ? null : Number(e.target.value) })} />
                </label>
                <Button type="button" variant="ghost" className="px-2" onClick={() => setRoles(roles.filter((_, j) => j !== i))} aria-label="Delete">×</Button>
              </div>
              <Err errors={errors} path={`human_roles.${i}.role`} />
              <Err errors={errors} path={`human_roles.${i}.min_count`} />
              <Err errors={errors} path={`human_roles.${i}.world_verified`} />
            </div>
          ))}
          <Err errors={errors} path="human_roles" />
          <Button type="button" variant="secondary" onClick={() => setRoles([...roles, { role: "approver", world_verified: true, min_count: null }])}>Add Role</Button>
        </div>
      </Field>
      <Err errors={errors} path="" />
    </div>
  );
}
