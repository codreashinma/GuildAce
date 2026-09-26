# database-design.md 改訂プロンプト（A: 内部矛盾の修正）

`database-design.md` の内部矛盾 7 件を修正してください。要件 ID・アーキテクチャ ID・DQ/AQ の番号は振り直さず、変更履歴に「2026-09-26 改訂（内部矛盾の修正）」を追加してください。指摘以外の箇所は変えないでください。

## 1. 承認者の集合が DB にもオンチェーンにも無い（5-2-7、6-1）

`approvals.role_label`（自由記述）と `_hasApproved` だけでは、誰が承認者かを判定できず、任意のアドレスが承認できてしまいます。NFR-003 が崩れます。

→ 案件単位に承認者アドレスの配列と必要承認数を持ち、発注者が案件開設時にオンチェーンで固定する構造にしてください。

- オフチェーン: `projects` に `approvers`（jsonb、小文字アドレスの配列、NOT NULL）と `threshold`（smallint、1 以上かつ approvers 件数以下の CHECK）を追加。
- オンチェーン: 案件ごとの struct（`client`, `token`, `approvers[]`, `threshold`）を追加し、`TaskEscrow.requiredApprovals` は案件側の `threshold` に置き換える。承認関数は「approver が案件の approvers に含まれること」を検証する。
- `approvals.role_label` は表示用として残してよい。

## 2. PM Agent をレビューできない（5-2-10、5-2-11）

`reviews.reviewee_user_id` はユーザーしか指せませんが、`reputations.subject_type` には `pm_agent` があります。コンセプト図の「★4.9（127 Human）」は PM Agent への評価です。

→ `reviews` を `target_type`（`user` / `pm_agent`）と `target_id`（論理参照、FK なし）に変更し、発注者→PM Agent と Human Task 受注者→発注者の 2 方向を許してください。一意制約は `(project_id, reviewer_user_id, target_type, target_id)`。自己評価禁止の CHECK は `target_type = 'user'` のときのみ適用。

## 3. Human Task の報酬が Escrow に載っていない（5-2-14）

`human_tasks.reward_amount` が `task_escrows` と繋がっておらず、FR-012 の自動支払いと CON-006 の「工程単位の預託」の対象外になっています。

→ Human Task は `tasks` の 1 行として扱い（`tasks` に `kind`（`ai` / `human`）を追加）、工程として預託してください。`human_tasks` は「指名・受諾・提出」の業務記録に限定し、`task_id`（FK tasks、UK）を持たせ、`requested_by_task_id` と `reward_amount` は削除してください。報酬は `tasks.amount` を参照します。

## 4. `payee` が預託時に不変（6-1、6-2）

Human Task は預託後に担当者が決まるため、`Funded` 時点で支払先を確定できません。

→ `payee` は成果物提出（`DeliverableSubmitted`）時に成果物ハッシュと一緒に確定し、承認は (deliverableHash, payee) の組に紐づける設計にしてください。`Funded` イベントから `payee` を外し、`DeliverableSubmitted` に `payee` を追加します。再提出でハッシュか支払先が変わったら承認カウントをリセットし、`_hasApproved` は「承認者 → 承認したハッシュ」の mapping にして古いハッシュへの承認を無効化してください。

## 5. `Held` の意味が曖昧（5-3、6-2）

「条件未達」の `Held` は、承認数が足りないだけの状態と紛争中の区別が付かず、`DisputeRaised` 後の状態も定義されていません。

→ 承認未達は `Submitted` のまま（保留は状態遷移ではなく「何も起きない」）とし、`Held` と `Held` イベントを削除。紛争は `Disputed` 状態を追加して `DisputeRaised` で遷移させ、裁定で `Released` / `Refunded` に遷移させてください。`escrow_status` と `task_status` の列挙、状態遷移図も合わせて更新してください。

## 6. `project-<seq>` の連番の採番主体が無い（6-4）

→ 採番テーブルを作らず、案件 UUID から決定的に導出する規則を書いてください（例: UUID 先頭 6 桁を 16 進整数として 1000 で割った余り）。衝突しうることと、衝突時は再導出ではなく UUID 全体のハッシュにフォールバックすることを注記してください。

## 7. 送信側のジョブテーブルが無い（5-1）

`chain_events` は取り込み側だけで、ADR-006 の「非同期ジョブ投入・冪等キー・再送」を担う表がありません。

→ `chain_jobs` を追加してください: `id`, `kind`（`fund_task` / `submit` / `approve` / `dispute` / `resolve` / `ens_publish` / `ens_update` / `ens_project`）, `idempotency_key`（UK）, `payload`（jsonb）, `status`（`queued` / `running` / `retry` / `done` / `failed`）, `attempts`, `tx_hash`, `error`, `next_attempt_at`, `finished_at`, `created_at`, `updated_at`。Escrow と ENS への書き込みはすべてこの表を経由し、冪等キーで二重送信を防ぐ旨を 7 章にも追記してください。

## 出力

5-1 テーブル一覧、5-2 の該当テーブル定義、5-3 列挙値と状態遷移図、6-1 / 6-2 のオンチェーン設計、7 章、ER 図（Mermaid）を上記に合わせて更新してください。DQ / AQ は変更しないでください。
