# データベース設計書

## 1. 概要

### 対象システム / 目的

AI Agent Marketplace（AI Agent × World × ENS）MVP のオフチェーン DB。PM Agent の作成・公開、案件の計画〜実行〜検収、Human-backed Review、Human Jury、Human Task Marketplace の状態を保持する。

### 前提・参照資料

| 資料 | 位置づけ |
|---|---|
| `docs/specs/20260925-agent-marketplace-mvp.md` | **正本**。機能仕様（F1〜F8）・状態遷移・技術方針はこれに従う |
| `docs/ETH_Globalユースケース.pdf` | 背景資料（企画段階のユースケース図 4 ページ） |
| `docs/01-アーキテクチャ図.svg` | 背景資料（企画段階の全体アーキテクチャ。マイルストーン / Permission Registry 等は MVP スコープ外） |
| `contracts/src/Escrow.sol` | Escrow のイベント・状態（`Deposited` / `Released` / `Resolved`）の確認に使用 |
| `docs/02-アーキテクチャ図-WorldMiniApp案.svg` | **不採用**（World Mini App は MVP のやらないこと） |

要件定義書は無く、仕様書をもって代替する。企画段階資料にある「部署ごとの承認権限」「工程（マイルストーン）」「成果物ハッシュ」は MVP 仕様書のスコープ外のためテーブル化していない。

### DBMS・文字コード・タイムゾーン・ID 方針

| 項目 | 方針 |
|---|---|
| DBMS | PostgreSQL 16（仕様書「技術方針」で確定。`docker-compose.yml` で起動） |
| 文字コード | UTF-8（`UTF8` / collation `C` または `en_US.UTF-8`。仮定） |
| タイムゾーン | すべて `timestamptz` で UTC 保存。表示側で変換 |
| 主キー | `uuid`（`gen_random_uuid()` をデフォルト） |
| 外部キー | `<単数形テーブル名>_id` |
| 監査カラム | 全テーブルに `created_at` / `updated_at`（`timestamptz NOT NULL DEFAULT now()`）。物理削除のみで `deleted_at` は持たない（MVP） |
| 金額 | USDC（MockUSDC, 6 decimals）の最小単位を `numeric(78,0)` で保持。表示時に 10^6 で割る |
| アドレス | `varchar(42)`、小文字正規化して保存。tx hash は `varchar(66)`（`0x` + 64 hex）小文字 |
| 列挙値 | `varchar` + `CHECK` 制約（Alembic での変更を容易にするため PostgreSQL `ENUM` 型は使わない） |
| 命名 | `snake_case`、テーブル名は複数形 |
| ORM / マイグレーション | SQLAlchemy 2 + Alembic |

## 2. データ配置方針

正本がオンチェーン（Escrow / ENS）または World にあるデータは、DB には参照 ID だけを持つ。表示や検索に必要な値はキャッシュとして複製し、その旨を明記する。

| 分類 | データ | 正本 | DB での扱い |
|---|---|---|---|
| DB が正本 | ユーザー、Agent の下書き・ルール（system prompt）、案件・タスク・Human Task・計画 JSON・成果物テキスト、レビュー本文、紛争の論点サマリー、Jury 投票 | PostgreSQL | そのまま保存 |
| オンチェーンが正本 | Escrow の預託額・状態（`Case.status`）、配分結果 | Escrow コントラクト（Sepolia） | `cases.escrow_case_id`（bytes32）、`deposit_tx_hash` / `release_tx_hash`、`disputes.resolve_tx_hash` の **参照 ID のみ**。残高・状態は `Escrow.getCase` / イベントを RPC で読む。`cases.status` はアプリの業務状態であり、API が tx receipt（`Deposited` 等）を検証してから遷移させる |
| オンチェーンが正本 | ENS subname の所有者・resolver、text record（`description`, `avatar`, `url`, `agent.*`） | ENSv2 Sepolia（PublicResolverV2） | `agents.ens_name` / `ens_tx_hash` は参照 ID。`description` / `category` / `fee_bps` / `payout_address` / `avatar_url` / `rating_avg` / `rating_count` / `completed_count` は **ENS text record のキャッシュ**（DB の値から `setText` で書き込む。詳細ページでは viem `getEnsText` で読んだ「ENS 上の値」を併記し、DB 値との差異を可視化する）。Agent 一覧の検索・並び替えは DB キャッシュで行う |
| 外部サービスが正本 | World ID の proof、人間性の検証結果 | World（Developer Portal verify API v4） | proof 本体は保存しない。検証成功時に返る `nullifier_hash` と `action` / `signal` を `world_verifications` に記録し、二重投稿・二重投票・多重受注の防止に使う。`users.human_verified` はその存在有無の非正規化 |
| 保存しない | 秘密鍵（サーバー署名者、RP 署名鍵）、JWT、SIWE nonce、Gemini API key | `.env` / メモリ | DB には持たない。SIWE nonce の永続化は未決事項（6 章） |
| 保存しない | 成果物ファイル | — | MVP は テキスト / Markdown / URL のみ（`tasks.deliverable`, `human_tasks.submission`）。オブジェクトストレージは未採用 |

個人情報: メールアドレス・氏名は扱わない。ウォレットアドレスと World ID の nullifier（仮名化済み識別子）のみを保持する。

## 3. テーブル一覧

| No | テーブル名 | 論理名 | 概要 | 関連ユースケース |
|---|---|---|---|---|
| 1 | `users` | ユーザー | ウォレットで SIWE ログインした利用者。発注者 / Creator / Worker / Jury の役割は行動で決まる（ロール列は持たない） | F1, F2, F4, F5, F6, F7 |
| 2 | `agents` | PM Agent | ユーザーが作成し ENS subname として公開する PM Agent。ENS text record のキャッシュを含む | F2, F3, F4, F5 |
| 3 | `cases` | 案件 | 発注者が PM Agent に依頼する案件。計画 JSON と Escrow 参照を持つ | F4, F5, F6, F8 |
| 4 | `tasks` | タスク | PM Agent の計画から生成された AI / Human タスクと成果物 | F4, F7 |
| 5 | `human_tasks` | Human Task | Human Task Marketplace に公開される人間向けタスク（`tasks` と 1:0..1） | F7, F4 |
| 6 | `reviews` | レビュー | World ID 検証済みの当事者による星評価・コメント | F5, F3 |
| 7 | `disputes` | 紛争 | 差し戻しで発生する紛争と AI 論点サマリー、Jury 結果 | F6, F4 |
| 8 | `jury_votes` | Jury 投票 | 第三者 Jury の 1 人 1 票 | F6 |
| 9 | `world_verifications` | World ID 検証 | World ID 検証結果（nullifier）の記録。重複防止の要 | F5, F6, F7 |

## 4. テーブル定義

共通: `id uuid PK DEFAULT gen_random_uuid()`、`created_at` / `updated_at timestamptz NOT NULL DEFAULT now()`。`updated_at` はアプリ（SQLAlchemy `onupdate`）で更新する。

### 4.1 `users`（ユーザー）

概要: SIWE 署名検証成功時に `wallet_address` で upsert する。役割（発注者 / Creator / Worker / Jury）は固定せず、各テーブルの FK で表す。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| wallet_address | ウォレットアドレス | varchar(42) | NO | | UK | 小文字正規化。SIWE の address |
| display_name | 表示名 | varchar(255) | YES | | | ENS 逆引き名（primary name）のキャッシュ。無ければ NULL でアドレスを表示 |
| human_verified | 人間確認済み | boolean | NO | false | | `world_verifications` に 1 件以上あれば true。ヘッダー表示用の非正規化 |
| last_login_at | 最終ログイン | timestamptz | YES | | | SIWE 検証成功時に更新 |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `users_wallet_address_key` (wallet_address) — UNIQUE。ログイン時の upsert キー
- 制約: `CHECK (wallet_address = lower(wallet_address))`

### 4.2 `agents`（PM Agent）

概要: PM Agent の定義。`rules` は Gemini に渡す system prompt。`status` が `published` になった時点で `ens_name` が確定し、`description` 以下の公開項目は ENS text record と同期する（キャッシュ）。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| creator_id | 作成者 | uuid | NO | | FK → users.id | PM Agent Creator |
| name | 名前 | varchar(100) | NO | | | 表示名 |
| label | ラベル | varchar(63) | NO | | UK | subname 用 slug。英小文字・数字・ハイフン。重複は 409 |
| description | 説明 | text | NO | | | ENS `description` のキャッシュ |
| category | カテゴリ | varchar(32) | NO | | | `web_dev` / `design` / `video` / `other`（Web開発 / デザイン / 動画制作 / その他）。ENS `agent.category` のキャッシュ |
| rules | 進め方・ルール | text | NO | | | system prompt。ENS には載せない（DB が正本） |
| fee_bps | 利用料 | integer | NO | | | bps（100 = 1%）。ENS `agent.fee_bps` のキャッシュ |
| payout_address | 受取アドレス | varchar(42) | NO | | | 小文字正規化。既定は作成者ウォレット。ENS `addr` レコードのキャッシュ |
| avatar_url | アイコン URL | varchar(2048) | YES | | | ENS `avatar` のキャッシュ（任意） |
| ens_name | ENS 名 | varchar(255) | YES | | UK | `<label>.choice.eth`。公開成功後に設定。参照 ID |
| ens_tx_hash | ENS 登録 tx | varchar(66) | YES | | | subname 発行 / text record 登録の tx hash（multicall で 1 tx 想定。2 tx になる場合は最後の hash） |
| status | 状態 | varchar(20) | NO | 'draft' | | `draft` / `publishing` / `published` / `publish_failed` |
| rating_avg | 平均評価 | numeric(2,1) | YES | | | 小数 1 桁。レビュー反映時に再計算。ENS `agent.rating` のキャッシュ。レビュー 0 件は NULL |
| rating_count | レビュー件数 | integer | NO | 0 | | ENS `agent.reviews` のキャッシュ |
| completed_count | 完了案件数 | integer | NO | 0 | | `cases.status=completed` になるたび +1。ENS `agent.completed` のキャッシュ |
| published_at | 公開日時 | timestamptz | YES | | | `published` になった日時 |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `agents_label_key` (label) — UNIQUE。`agents_ens_name_key` (ens_name) — UNIQUE（NULL は複数可）。`idx_agents_creator_id` (creator_id)。`idx_agents_marketplace` (status, category, rating_avg DESC) — マーケットプレイスのカテゴリ絞り込み・評価順
- 制約: `CHECK (label ~ '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$')`、`CHECK (fee_bps BETWEEN 0 AND 10000)`、`CHECK (status IN ('draft','publishing','published','publish_failed'))`、`CHECK (rating_avg IS NULL OR rating_avg BETWEEN 1.0 AND 5.0)`、`CHECK (payout_address = lower(payout_address))`。FK `creator_id` は `ON DELETE RESTRICT`
- 非正規化: `rating_avg` / `rating_count` / `completed_count` は `reviews` / `cases` から集計可能だが、一覧のソートと ENS への書き込み値を一致させるため保持する

### 4.3 `cases`（案件）

概要: 発注者が PM Agent に依頼する案件。状態遷移は `draft → planning → awaiting_approval → funded → in_progress → delivered → completed | disputed → resolved`、計画失敗時は `planning_failed`。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| client_id | 発注者 | uuid | NO | | FK → users.id | |
| agent_id | PM Agent | uuid | NO | | FK → agents.id | 利用する PM Agent（`published` のもの） |
| title | タイトル | varchar(200) | NO | | | |
| description | 説明 | text | NO | | | 依頼内容 |
| budget | 予算 | numeric(78,0) | NO | | | USDC 最小単位（300 USDC = 300000000）。Escrow への預託額 |
| deadline | 納期 | date | YES | | | 期限で資金は動かない（表示用） |
| status | 状態 | varchar(20) | NO | 'draft' | | `draft` / `planning` / `planning_failed` / `awaiting_approval` / `funded` / `in_progress` / `delivered` / `completed` / `disputed` / `resolved` |
| plan_json | 計画 JSON | jsonb | YES | | | Gemini が生成した `{tasks[], team[], pm_fee, total}` の原文。`tasks` テーブルはここから展開する（監査用に原文も残す） |
| escrow_case_id | Escrow 案件 ID | varchar(66) | YES | | UK | `bytes32` の hex（`0x` + 64 hex、小文字）。`deposit` 時に API が `id` から導出（例: `keccak256(cases.id)`）。参照 ID |
| deposit_tx_hash | 入金 tx | varchar(66) | YES | | | `Escrow.deposit` の tx hash。`Deposited` 検証後に設定 |
| release_tx_hash | 支払 tx | varchar(66) | YES | | | `Escrow.release` の tx hash（`completed` 時）。Jury 経由の `resolve` は `disputes.resolve_tx_hash` |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `cases_escrow_case_id_key` (escrow_case_id) — UNIQUE。`idx_cases_client_id_created_at` (client_id, created_at DESC) — 自分の案件一覧。`idx_cases_agent_id_status` (agent_id, status) — Agent 実績・完了数集計
- 制約: `CHECK (budget > 0)`、`CHECK (status IN (...上記 10 値...))`。FK `client_id` / `agent_id` は `ON DELETE RESTRICT`
- 備考: Escrow 上の残高・`Case.status` は DB に持たず RPC で読む。`status` と `deposit_tx_hash` の整合は API の receipt 検証で担保する

### 4.4 `tasks`（タスク）

概要: `cases.plan_json` の `tasks[]` を承認時（または計画生成時）に展開した実行単位。`type=ai` は Gemini が成果物を生成、`type=human` は `human_tasks` 経由で人間が実行する。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| case_id | 案件 | uuid | NO | | FK → cases.id | |
| order_no | 実行順 | integer | NO | | | 1 始まり。案件内で一意 |
| title | タイトル | varchar(200) | NO | | | |
| description | 説明 | text | NO | | | 完了条件を含む |
| type | 種別 | varchar(10) | NO | | | `ai` / `human` |
| role | 役割 | varchar(20) | NO | | | `designer` / `frontend` / `backend` / `qa` / `field` |
| estimated_cost | 見積額 | numeric(78,0) | NO | | | USDC 最小単位。Σ + PM fee ≤ budget |
| status | 状態 | varchar(20) | NO | 'todo' | | `todo` / `in_progress` / `done` |
| assignee_name | 担当 Agent 名 | varchar(100) | YES | | | `team[]` の AI 専門 Agent 名（例: Designer Agent）。human の場合は NULL（担当は `human_tasks.worker_id`） |
| deliverable | 成果物 | text | YES | | | Markdown / URL。human の場合は `human_tasks.submission` を `done` 時にコピー |
| completed_at | 完了日時 | timestamptz | YES | | | |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `tasks_case_id_order_no_key` (case_id, order_no) — UNIQUE、案件ボードの並び順
- 制約: `CHECK (type IN ('ai','human'))`、`CHECK (role IN ('designer','frontend','backend','qa','field'))`、`CHECK (status IN ('todo','in_progress','done'))`、`CHECK (estimated_cost >= 0)`。FK `case_id` は `ON DELETE CASCADE`
- 備考: 全タスクが `done` になったら API が `cases.status` を `delivered` にする

### 4.5 `human_tasks`（Human Task）

概要: `tasks.type=human` を Human Task Marketplace に公開したレコード。受注（World ID `human-task`）・提出・AI 照合を経て `done` になる。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| task_id | 元タスク | uuid | NO | | FK → tasks.id, UK | 1 タスクにつき 1 件 |
| case_id | 元案件 | uuid | NO | | FK → cases.id | 一覧で「元案件 / 依頼元 PM Agent」を 1 JOIN で引くための冗長 FK（`tasks.case_id` と一致させる） |
| title | タイトル | varchar(200) | NO | | | 公開時に `tasks.title` からコピー（Marketplace 向けに編集可能） |
| description | 内容 | text | NO | | | 完了条件を含む |
| reward | 報酬 | numeric(78,0) | NO | | | USDC 最小単位。通常 `tasks.estimated_cost`。`release` 配分の worker 分 |
| status | 状態 | varchar(20) | NO | 'open' | | `open` / `accepted` / `submitted` / `done`。提出前キャンセルで `open` に戻し `worker_id` を NULL に |
| worker_id | Worker | uuid | YES | | FK → users.id | 受注者。`open` では NULL |
| submission | 提出物 | text | YES | | | テキスト / URL |
| ai_check | AI 照合 | text | YES | | | PM Agent（Gemini）による完了条件との照合コメント |
| accepted_at | 受注日時 | timestamptz | YES | | | |
| submitted_at | 提出日時 | timestamptz | YES | | | |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `human_tasks_task_id_key` (task_id) — UNIQUE。`idx_human_tasks_status_created_at` (status, created_at DESC) — `open` 一覧。`idx_human_tasks_worker_id` (worker_id) — 自分の受注一覧
- 制約: `CHECK (status IN ('open','accepted','submitted','done'))`、`CHECK (status = 'open' OR worker_id IS NOT NULL)`、`CHECK (reward >= 0)`。FK `task_id` / `case_id` は `ON DELETE CASCADE`、`worker_id` は `ON DELETE RESTRICT`
- 非正規化: `case_id` は `tasks` から導出可能だが、一覧表示の JOIN 削減と `worker` が案件当事者かの判定（F5 / F6）を簡潔にするため保持する

### 4.6 `reviews`（レビュー）

概要: 案件 `completed` / `resolved` 後に当事者（発注者・Human Task Worker）が投稿する星評価。World ID（action `review`, signal = caseId）で人間確認済み。Agent 対象の場合は `agents.rating_avg` / `rating_count` を再計算し ENS に反映する。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| case_id | 案件 | uuid | NO | | FK → cases.id | |
| reviewer_id | 投稿者 | uuid | NO | | FK → users.id | 案件の当事者 |
| target_type | 対象種別 | varchar(10) | NO | | | `agent` / `user` |
| target_id | 対象 ID | uuid | NO | | | `agent` なら agents.id、`user` なら users.id（ポリモーフィック参照のため FK なし。アプリで存在検証） |
| rating | 星 | smallint | NO | | | 1〜5 |
| comment | コメント | text | YES | | | |
| nullifier | nullifier | varchar(66) | NO | | | World ID `nullifier_hash`。「World で人間確認済み」バッジの根拠 |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `reviews_case_id_nullifier_key` (case_id, nullifier) — UNIQUE、同一人物の同一案件二重投稿を防ぐ（`world_verifications` の UNIQUE と二重に担保）。`idx_reviews_target` (target_type, target_id, created_at DESC) — Agent 詳細のレビュー一覧・平均再計算
- 制約: `CHECK (target_type IN ('agent','user'))`、`CHECK (rating BETWEEN 1 AND 5)`。FK `case_id` / `reviewer_id` は `ON DELETE RESTRICT`（評価集計の根拠を残す）

### 4.7 `disputes`（紛争）

概要: 発注者の「差し戻し」で作成。Gemini が論点サマリーを生成し（AI は判断しない）、Jury 3 票の多数決で `outcome` が決まり、サーバー署名者（arbiter）が `Escrow.resolve` を送信して `closed` にする。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| case_id | 案件 | uuid | NO | | FK → cases.id, UK | MVP では案件ごとに 1 紛争 |
| reason | 差し戻し理由 | text | NO | | | 発注者入力 |
| summary_json | 論点サマリー | jsonb | YES | | | `{issues[], client_claims[], contractor_claims[], facts_to_verify[], ai_opinion}`。生成前は NULL |
| status | 状態 | varchar(10) | NO | 'open' | | `open` / `closed` |
| outcome | 結果 | varchar(10) | YES | | | `release` / `refund`。3 票の多数決で確定 |
| resolve_tx_hash | 仲裁 tx | varchar(66) | YES | | | `Escrow.resolve` の tx hash。参照 ID |
| closed_at | 終了日時 | timestamptz | YES | | | |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `disputes_case_id_key` (case_id) — UNIQUE。`idx_disputes_status_created_at` (status, created_at DESC) — Jury 画面の `open` 一覧
- 制約: `CHECK (status IN ('open','closed'))`、`CHECK (outcome IS NULL OR outcome IN ('release','refund'))`、`CHECK (status = 'open' OR outcome IS NOT NULL)`。FK `case_id` は `ON DELETE RESTRICT`

### 4.8 `jury_votes`（Jury 投票）

概要: World ID（action `jury`, signal = disputeId）で人間確認済みの、当事者でない第三者の投票。1 人 1 票。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| dispute_id | 紛争 | uuid | NO | | FK → disputes.id | |
| voter_id | 投票者 | uuid | NO | | FK → users.id | 当事者（発注者、Agent 作成者、Worker）は 403（アプリで判定） |
| vote | 票 | varchar(10) | NO | | | `release` / `refund` |
| nullifier | nullifier | varchar(66) | NO | | | World ID `nullifier_hash` |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `jury_votes_dispute_id_voter_id_key` (dispute_id, voter_id) — UNIQUE。`jury_votes_dispute_id_nullifier_key` (dispute_id, nullifier) — UNIQUE、別ウォレットでの同一人物二重投票を防ぐ
- 制約: `CHECK (vote IN ('release','refund'))`。FK `dispute_id` は `ON DELETE CASCADE`、`voter_id` は `ON DELETE RESTRICT`
- 備考: 3 票目の INSERT と `disputes.outcome` 確定は同一トランザクションで行い、`SELECT ... FOR UPDATE` で紛争行をロックして 4 票目を防ぐ

### 4.9 `world_verifications`（World ID 検証）

概要: Developer Portal verify API v4 での検証成功を記録する。proof 本体は保存せず、`nullifier_hash` のみ持つ。`(action, signal, nullifier)` UNIQUE により、同じ人間が同じ対象（案件 / 紛争 / タスク）に対して 1 回しかアクションできない。

| カラム名 | 論理名 | 型 | NULL | デフォルト | キー | 説明 |
|---|---|---|---|---|---|---|
| id | ID | uuid | NO | gen_random_uuid() | PK | |
| user_id | ユーザー | uuid | NO | | FK → users.id | 検証時にログインしていたユーザー |
| action | action | varchar(32) | NO | | | `review` / `jury` / `human-task`（Portal に作成した 3 action） |
| signal | signal | varchar(255) | NO | | | caseId / disputeId / taskId（UUID 文字列） |
| nullifier | nullifier | varchar(66) | NO | | | `nullifier_hash`（`0x` + 64 hex）。同一 action 内では同一人物で不変 |
| verified_at | 検証日時 | timestamptz | NO | now() | | verify API 成功時刻 |
| created_at | 作成日時 | timestamptz | NO | now() | | |
| updated_at | 更新日時 | timestamptz | NO | now() | | |

- インデックス: `world_verifications_action_signal_nullifier_key` (action, signal, nullifier) — UNIQUE、重複は 409。`idx_world_verifications_user_id` (user_id) — `users.human_verified` の更新・自分の検証履歴
- 制約: `CHECK (action IN ('review','jury','human-task'))`。FK `user_id` は `ON DELETE CASCADE`
- 備考: World ID の nullifier は action ごとに同一人物で同じ値になるため、`(action, nullifier)` で「同じ人間が複数ウォレットを使っている」ことも検出できる（MVP では利用しない）

## 5. ユースケースとの対応

| ユースケース | 参照テーブル | 更新テーブル |
|---|---|---|
| F1 ウォレットログイン（SIWE） | users | users（upsert、`last_login_at`） |
| F2 PM Agent 作成（下書き） | users | agents（`draft`） |
| F2 PM Agent 公開（ENS subname + text record） | agents | agents（`publishing` → `published` / `publish_failed`、`ens_name`, `ens_tx_hash`, `published_at`） |
| F3 マーケットプレイス一覧・検索 | agents | — |
| F3 Agent 詳細（ENS 実値 + レビュー + 実績） | agents, reviews, users, cases | — |
| F4 案件作成 | agents, users | cases（`draft` → `planning`） |
| F4 計画生成（Gemini） | cases, agents | cases（`plan_json`, `awaiting_approval` / `planning_failed`）, tasks |
| F4 承認＋入金（receipt 検証） | cases | cases（`escrow_case_id`, `deposit_tx_hash`, `funded` → `in_progress`）, human_tasks（`type=human` を `open` で公開） |
| F4 AI タスク実行 | tasks, agents | tasks（`deliverable`, `done`）, cases（全 done で `delivered`） |
| F4 検収・承認して支払う | cases, tasks, human_tasks, agents, users | cases（`release_tx_hash`, `completed`）, agents（`completed_count` → ENS `agent.completed`） |
| F4 差し戻す | cases | cases（`disputed`）, disputes（`open`） |
| F5 rp_context 取得 / proof 検証 | users | world_verifications |
| F5 レビュー投稿 | cases, human_tasks, world_verifications | reviews, agents（`rating_avg`, `rating_count` → ENS `agent.rating` / `agent.reviews`）, users（`human_verified`） |
| F6 論点サマリー生成 | cases, tasks, human_tasks, disputes | disputes（`summary_json`） |
| F6 Jury 一覧・投票 | disputes, cases, human_tasks, agents, world_verifications | jury_votes, world_verifications |
| F6 3 票確定 → Escrow.resolve | disputes, jury_votes, cases, agents, human_tasks, users | disputes（`outcome`, `resolve_tx_hash`, `closed`）, cases（`resolved`） |
| F7 Human Task 一覧 | human_tasks, cases, agents | — |
| F7 受注 / キャンセル | human_tasks, world_verifications | human_tasks（`accepted` / `open`）, world_verifications |
| F7 提出 → AI 照合 → done | human_tasks, tasks | human_tasks（`submitted` → `done`, `ai_check`）, tasks（`deliverable`, `done`） |
| F8 Escrow コントラクト | cases（`escrow_case_id`, tx hash） | — （状態はオンチェーンが正本） |
| シード投入（`scripts/seed.py`） | — | users, agents, cases, tasks, human_tasks, reviews |

## 6. 未決事項・確認事項

- [ ] **SIWE nonce の保存先**: `GET /auth/nonce` で発行する nonce を DB テーブル（`auth_nonces`）に置くか、API プロセス内メモリ / Redis に置くか。MVP は単一プロセスのためメモリ想定で、テーブルは作っていない。
- [ ] **`cases.escrow_case_id` の導出規則**: `keccak256(cases.id)` か、`cases.id` の UUID 16 バイトを左詰めした bytes32 か。フロント（viem）と API（web3.py）で同じ関数を使う必要がある。
- [ ] **計画の再生成と `tasks` の扱い**: 予算超過での再生成（最大 2 回）や `planning_failed` からの再試行時に、`tasks` を DELETE して再展開するか、`plan_json` のみ更新し承認時に展開するか。本設計は「承認時に展開」を推奨するが、承認画面でタスク一覧を出すため生成時展開でも可。
- [ ] **紛争の複数回発生**: `disputes.case_id` を UNIQUE にしている（案件ごと 1 回）。企画資料の「修正して再提出 → 改めて承認」（続ける場合）を MVP 後に入れるなら UNIQUE を外し `round` 列を追加する。
- [ ] **`reviews.target_type='user'` のユースケース**: 仕様書 F5 は「対象が Agent の場合は…」とあり、User 対象（発注者 → Worker、Worker → 発注者）の表示先・集計先が未定義。テーブルは両対応にしてある。
- [ ] **Agent 作成者は Jury の当事者か**: F6「当事者でない」の範囲に PM Agent の作成者（`agents.creator_id`）を含めるか。本設計は含める前提で 4.8 に記載。
- [ ] **ENS キャッシュの整合**: ENS `setText` が失敗した場合（`agent.rating` 更新など）に DB 値を巻き戻すか、`ens_sync_pending` のような再送フラグを持つか。仕様書の未決事項「ENS 書き込みキュー」フォールバックを採用するなら `ens_write_jobs` テーブル（agent_id, key, value, status, tx_hash）を追加する。
- [ ] **`users.display_name` の更新タイミング**: ENS 逆引きをログイン時に毎回引くか、キャッシュ有効期限を持つか。
- [ ] **列挙値の物理表現**: `varchar + CHECK` を仮定。SQLAlchemy `Enum(native_enum=False)` で実装する想定。
- [ ] **文字コード / collation**: `UTF8` を仮定（docker-compose の `postgres:16` 既定）。日本語検索は `ILIKE` のみで全文検索は行わない。

## 7. 変更履歴

| 日付 | 内容 |
|---|---|
| 2026-09-25 | 初版作成（仕様書 `20260925-agent-marketplace-mvp.md` に基づく 9 テーブル） |

## 8. 実装との対応メモ（2026-09-25 実装後）

- `cases.escrow_case_id` は `keccak256(utf8(case.id))` の bytes32（`apps/api/app/services/chain.py: escrow_case_id`）。
- 実装（`apps/api/app/models.py`）は本設計書のうち補助カラム（`users.human_verified` / `last_login_at`、`agents.avatar_url` / `published_at`、`human_tasks.accepted_at` / `submitted_at`、`disputes.closed_at`、`world_verifications.verified_at`）を持たず、代わりに `agents.ens_error`、`cases.error`、`disputes.required_votes` を持つ。MVP ではマイグレーションを使わず `create_all` で生成している。
- 紛争は案件ごとに 1 件、`reviews.target_type='user'` は Human Task worker → 発注者 のレビューとして保存のみ（表示は案件詳細）。

## 9. 追加テーブル（2026-09-25 アーキテクチャ整合後）

| テーブル | 役割 | 主なカラム |
|---|---|---|
| `companies` | 受注側の会社（自社の `.eth` を所有） | admin_id, name, ens_name(UK), ens_verified |
| `members` | 会社の人員。ENS 名 `<label>.<company>` の record キャッシュ | company_id, label, wallet_address, ens_name, role, skills, location, available, ens_status, rating_avg, completed_count。UK(company_id,label) |
| `approvals` | 承認者の承認（World nullifier + EIP-712 署名）。オンチェーンへは worker が中継 | task_id, approver_id, deliverable_hash, signature, nullifier。UK(task_id, approver_id, deliverable_hash) |
| `chain_jobs` | チェーン連携ワーカーのジョブ（ADR-006） | kind, idempotency_key(UK), payload(jsonb), status(queued/running/retry/done/failed), attempts, tx_hash, error |

`tasks` に追加: `escrow_task_id`, `chain_status`（none/funded/submitted/paid/disputed/resolved = Escrow の投影）, `deliverable_hash`, `payee`, `approval_count`, `chain_tx_hash`。
`cases` に追加: `approvers`(jsonb), `threshold`, `open_tx_hash`, `project_ens_name`, `project_ens_tx_hash`, `request_nullifier`。`deposit_tx_hash` / `release_tx_hash` は廃止。
`human_tasks` に追加: `assignee_member_id`, `assignment_reason`, `declined_member_ids`(jsonb)。status に `assigned` を追加。
