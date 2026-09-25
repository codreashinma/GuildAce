# AI Agent Marketplace（AI Agent × World × ENS）MVP 仕様書

> 作成日: 2026-09-25
> 対象: ETHGlobal Tokyo ハッカソン提出用 MVP
> 参照資料: `docs/ETH_Globalユースケース.pdf`、`docs/01-アーキテクチャ図.svg`、ユーザー提示のコンセプト図3枚（World×ENS訴求 / 開発するもの / サービス全体像）

## 目的

AI Agent（PM Agent）が案件を受け、タスク分解・チーム編成・実行・納品・支払いまでを自律的に進める B2B マーケットプレイスを作る。
「重要な判断・評価・人間にしかできない作業」は **World ID で証明された実在の人間**が行い、Agent の **名前・公開情報・権限**は **ENS（ENSv2 / Sepolia）** に置く。

- **World への訴求**: Human-backed Review / Human Jury / Human Task Marketplace の3機能で「人間の希少性」をインフラ化する。
- **ENS への訴求**: PM Agent を `<agent>.<parent>.eth` の subname として公開し、プロフィールを text record に載せ、他サービスからも参照できるポータブルな Agent Identity にする。

## スコープ

### やること（MVP）

1. **PM Agent 作成・公開（ENS 連携）**: ユーザーが PM Agent を作成し、ENSv2 Sepolia 上に subname を発行、プロフィールを text record に登録する。
2. **Agent マーケットプレイス**: ENS から取得した Agent 一覧をカテゴリ・評価で閲覧・検索する。
3. **案件作成〜AI 自律実行**: 発注者が案件を作成 → PM Agent（Gemini）がタスク分解・チーム編成 → 発注者が計画承認と同時に Escrow へ入金 → AI タスクは自動実行、Human Task は人間が実行 → 成果物提出。
4. **検収・支払い**: 発注者が成果物を確認して承認すると Escrow から支払い（Sepolia、Mock USDC）。
5. **Human-backed Review**: 案件完了後、World ID 検証済みの当事者のみが星評価＋コメントを投稿。Agent の評価は ENS text record にも反映する。
6. **Human Jury**: 発注者が差し戻し → AI が論点整理 → World ID 検証済みの第三者 3 名が「支払い / 返金」を投票 → 多数決結果を Escrow に反映。
7. **Human Task Marketplace**: PM Agent が生成した「人間向けタスク」を一覧化し、World ID 検証済みの人間が受注・成果物提出・完了できる。
8. **ウォレットログイン**: wagmi + RainbowKit + SIWE。

### やらないこと

- 本番運用レベルのセキュリティ・スケーラビリティ（鍵管理は `.env`、Relayer / Paymaster なし）
- 実通貨・実 USDC（Mock USDC のみ）、メインネット、複数チェーン
- World Mini App（MiniKit）対応、モバイル最適化
- 実在する外部の受注企業のオンボーディング（受注側の「専門 Agent」は Gemini でシミュレートする）
- Agent 同士の自律取引、プロジェクト専用 subname（`project-xxx.web-pm...`）の自動発行 → 拡張として設計だけ残す
- 成果物ファイルのアップロード（成果物はテキスト / Markdown / URL のみ）
- ENSv1（NameWrapper）対応。ENSv2 Sepolia ベータのみ
- メール通知、チャット

## ユーザーストーリー

| ロール | ストーリー |
|---|---|
| PM Agent Creator | 自分の PM Agent（名前・説明・カテゴリ・進め方・利用料）を作成し「公開」を押すと、`web-pm.<parent>.eth` が発行され、マーケットプレイスに並ぶ |
| 発注者 | マーケットプレイスで PM Agent を選び「Web サービスを作りたい / 予算 300 USDC」と依頼すると、Agent がタスク計画とチーム案を出す。承認と同時に Escrow に 300 USDC を預ける |
| 発注者 | 進捗ボードで AI タスクの成果物が自動で積み上がるのを見る。全タスク完了後、検収して「承認」すると支払いが実行される |
| 発注者 / 受注側 | 完了後、World ID で人間確認をしてレビューを投稿する。Agent の評価が ENS に反映される |
| 発注者 | 納得できなければ「差し戻し」。AI が論点を整理し、Human Jury に回る |
| Jury（第三者） | World ID で人間確認をして、論点サマリーを読み「支払い / 返金」に投票する。3票集まると Escrow が実行される |
| Human Task Worker | Human Task 一覧から「現地の写真を撮ってきて」等を World ID 確認のうえ受注し、成果物（テキスト / URL）を提出する |

## 機能仕様

### F1. 認証（ウォレットログイン / SIWE）

- 入力: ウォレット接続（RainbowKit）→ `GET /auth/nonce` → SIWE メッセージ署名 → `POST /auth/verify`
- 処理: API が署名を検証し、`users` を upsert（`wallet_address` 小文字正規化）。JWT を発行し、以降の API は `Authorization: Bearer` で認証。
- 出力: ユーザー情報（address、ENS 逆引き名があれば表示名、`human_verified` フラグ）。
- エッジ: 署名失敗・nonce 不一致は 401。

### F2. PM Agent 作成・公開（ENS）

- 入力（作成画面）: 名前、ラベル（subname 用 slug。英小文字・数字・ハイフン）、説明、カテゴリ（Web開発 / デザイン / 動画制作 / その他）、進め方・ルール（system prompt になる自由文）、利用料（%）、受取アドレス（既定は作成者のウォレット）。
- 処理:
  1. `agents` に `status=draft` で保存。
  2. 「公開する」で API のサーバー署名ウォレット（プラットフォームが所有する親名 `<parent>.eth` の所有者）が ENSv2 Sepolia に対して
     - 親名の Registry に `register(label, owner=サーバー署名者, subregistry=0, resolver=PublicResolverV2, roleBitmap, expiry)` で subname を発行
     - resolver `multicall([setAddr(node, 受取アドレス), setText(...)])` でプロフィールを登録
  3. tx hash と `ens_name` を保存し `status=published`。
- ENS text record キー:
  | key | 値 |
  |---|---|
  | `description` | 説明 |
  | `avatar` | アイコン URL（任意） |
  | `url` | Agent 詳細ページ URL |
  | `agent.category` | カテゴリ |
  | `agent.fee_bps` | 利用料（bps） |
  | `agent.creator` | 作成者アドレス |
  | `agent.endpoint` | API の Agent エンドポイント URL |
  | `agent.rating` | 平均評価（小数1桁）※レビュー反映時に更新 |
  | `agent.reviews` | レビュー件数 |
  | `agent.completed` | 完了案件数 |
- 出力: 公開済み Agent（ENS 名、Etherscan / ENS App へのリンク）。
- エッジ: ラベル重複は 409。tx 失敗時は `status=publish_failed` にして再試行可能。ENS 書き込み中はスピナーと tx hash を表示。
- 補足（時間があれば）: 接続ウォレットが Sepolia ENSv2 の名前を所有していれば、その名前の下に subname を発行する（ユーザーが tx に署名）。既定はプラットフォーム親名。

### F3. Agent マーケットプレイス

- 入力: カテゴリ、キーワード、並び順（評価 / 完了数 / 新着）。
- 処理: `agents` を検索。詳細ページは ENS の text record を **viem の `getEnsText`（UniversalResolverV2 経由）で直接読み**、DB と並べて表示（「ENS 上の値」であることを明示）。
- 出力: 一覧カード（名前、ENS 名、★評価（n Human）、Fee、Completed、カテゴリ）、詳細ページ（プロフィール、レビュー一覧、実績、ENS レコード）。

### F4. 案件作成〜AI 自律実行

状態遷移: `draft → planning → awaiting_approval → funded → in_progress → delivered → completed | disputed → resolved`

- **作成**: 入力 = タイトル、説明、予算（USDC）、納期、利用する PM Agent。`cases` を `draft` で保存し即 `planning` へ。
- **計画（PM Agent）**: Gemini に Agent の「進め方・ルール」を system prompt として渡し、JSON で以下を生成する。
  - `tasks[]`: `{title, description, type: "ai" | "human", role: "designer"|"frontend"|"backend"|"qa"|"field", estimated_cost, order}`
  - `team[]`: AI 専門 Agent の名前・役割（例: Designer Agent / Frontend Agent）
  - 予算チェック: `Σestimated_cost + PM fee ≤ 予算`。超える場合は再生成（最大2回）、それでも超えれば発注者に「予算不足」を提示。
  - 保存後 `awaiting_approval`。
- **承認＋入金**: 発注者が計画を確認し「承認して入金」。フロントで `MockUSDC.approve(Escrow, amount)` → `Escrow.deposit(caseId, token, amount)`。API は tx receipt を検証（`Deposited` イベント）して `funded` → `in_progress`。
- **実行**:
  - `type=ai` のタスクは順に Gemini で成果物（Markdown）を生成し `deliverables` に保存、タスクを `done` に。（バックグラウンドジョブ。デモでは 1 タスク 5〜15 秒程度）
  - `type=human` のタスクは `human_tasks` に公開（F7）。
  - すべてのタスクが `done` になると `delivered`。
- **検収**: 発注者が成果物一覧を確認し
  - 「承認して支払う」→ フロントで `Escrow.release(caseId, recipients[], amounts[])` に署名（配分 = PM Agent の受取アドレスに fee、Human Task worker に各タスク額、残りも PM Agent 受取へ。API が配分を計算して表示）→ `completed`。Agent の `completed` text record を更新。
  - 「差し戻す」→ 理由を入力 → `disputed`（F6）。
- 出力: 案件ボード（ToDo / 進行中 / レビュー / 完了）、タスクごとの成果物ビューア、Escrow 残高・tx リンク。
- エッジ: Gemini の JSON パース失敗は 1 回リトライ、失敗で `planning_failed` を表示。入金 tx が確認できない場合は `awaiting_approval` のまま「入金を確認できません」を表示。

### F5. Human-backed Review

- 前提: 案件が `completed` または `resolved`。投稿者は案件の当事者（発注者、または Human Task worker）。
- 入力: 星（1〜5）、コメント、World ID proof。
- 処理:
  1. フロントで IDKit v4 `IDKitRequestWidget`（preset `proofOfHuman`、action `review`、signal = `caseId`）。`rp_context` は `GET /world/rp-context?action=review` で API が `signRequest` して返す。
  2. `POST /reviews` に proof を同送。API が `https://developer.world.org/api/v4/verify/{rp_id}` で検証し、`nullifier` を `world_verifications(action, signal, nullifier)` に UNIQUE 保存。重複は 409（同じ人間が同じ案件に二重投稿できない）。
  3. `reviews` 保存。対象が Agent の場合は平均・件数を再計算して ENS `agent.rating` / `agent.reviews` を `setText` で更新。
- 出力: Agent 詳細のレビュー一覧（「World で人間確認済み」バッジ付き）。
- エッジ: proof 検証失敗は 400 で理由を表示。当事者以外は 403。

### F6. Human Jury（紛争仲裁）

- 起点: F4「差し戻す」。`disputes` を作成。
- 処理:
  1. Gemini が「発注条件・成果物・差し戻し理由」から **論点サマリー**（争点、双方の主張、確認すべき事実、AI の参考所見）を生成し保存。※AI は判断しない。
  2. Jury 画面に `open` な紛争を一覧。World ID 検証済み（action `jury`、signal = `disputeId`）かつ **当事者でない**ユーザーが `release`（支払い）/ `refund`（返金）に投票。1 人 1 票（nullifier UNIQUE）。
  3. 3 票集まった時点で多数決。API のサーバー署名者（Escrow の `arbiter`）が `Escrow.resolve(caseId, recipients[], amounts[])` を送信（release なら通常配分、refund なら全額発注者）。案件を `resolved`、紛争を `closed`。
- 出力: 論点サマリー、投票状況（n/3）、結果と tx リンク。
- エッジ: 当事者の投票は 403。票が揃うまで資金は保留（期限で動かない）。

### F7. Human Task Marketplace

- 一覧: `human_tasks` の `open` を表示（タイトル、内容、報酬、元案件、依頼元 PM Agent）。
- 受注: World ID 検証（action `human-task`、signal = `taskId`）→ `accepted`（worker = 自分）。同一人物の多重受注は nullifier で防止。
- 提出: テキスト / URL を提出 → `submitted` → PM Agent（Gemini）が完了条件との照合コメントを生成し `done`（自動承認。MVP では人間の検収は F4 の発注者検収に集約）。
- 支払い: F4 の `release` 配分に worker 分が含まれる。
- エッジ: 受注済みタスクは他ユーザーに非表示。提出前にキャンセル可（`open` に戻す）。

### F8. Escrow コントラクト（Solidity / Foundry / Sepolia）

```solidity
struct Case { address client; address token; uint256 amount; Status status; }
enum Status { None, Funded, Released, Resolved }

function deposit(bytes32 caseId, address token, uint256 amount) external;            // 発注者。transferFrom
function release(bytes32 caseId, address[] recipients, uint256[] amounts) external;  // 発注者のみ。Σamounts == amount
function resolve(bytes32 caseId, address[] recipients, uint256[] amounts) external;  // arbiter のみ（Jury 結果）。Σamounts == amount
event Deposited(bytes32 indexed caseId, address indexed client, uint256 amount);
event Released(bytes32 indexed caseId);
event Resolved(bytes32 indexed caseId);
```

- `MockUSDC`: 6 decimals、誰でも `mint(address,uint256)` 可（フォーセット）。
- 不変条件: 期限では資金は動かない。AI は tx を送らない（resolve は Jury の多数決結果のみ）。
- テスト: Foundry で deposit / release / resolve / 不正呼び出し（他人の release、合計不一致）を検証。

## 技術方針

| 領域 | 採用 |
|---|---|
| モノレポ | `apps/web`（Next.js）、`apps/api`（FastAPI）、`contracts`（Foundry）、`docker-compose.yml`（PostgreSQL） |
| フロント | Next.js 15 App Router, TypeScript, Tailwind, wagmi v2 + viem + RainbowKit, `@worldcoin/idkit` v4, TanStack Query |
| バックエンド | Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, PostgreSQL 16, `google-genai`（Gemini、モデルは env `GEMINI_MODEL`、既定 `gemini-2.5-flash`）, `web3.py`（ENS 書き込み・Escrow resolve・receipt 検証）, `siwe`, PyJWT |
| チェーン | Sepolia。Escrow / MockUSDC を Foundry でデプロイ。RPC は env |
| ENS | ENSv2 Sepolia ベータ（UniversalResolverV2 `0x5d25c1d6acbb71b7a28aa7899618a3412a8303e3`、PublicResolverV2 `0xd7e590ad0e92a6ac1d81f4483a9b951d3585a50f`、ETHRegistrar `0xabe76f6c8dfced81aa5a2bb8034202a7136b94ca`）。親名はプラットフォーム用に 1 つ登録（登録料は MockUSDC）。読み取りは viem、書き込みは API のサーバー署名者 |
| World | IDKit v4 + RP 署名（`RP_SIGNING_KEY`）+ Developer Portal verify API v4。action は `review` / `jury` / `human-task` の 3 つを Portal に作成 |
| AI | すべて `apps/api/app/agents/` に集約。PM Agent の「進め方・ルール」を system prompt として注入。出力は JSON schema で強制 |
| 認証 | SIWE + JWT（HS256、24h） |
| 環境変数 | `.env.example` に全項目と取得手順（Sepolia ETH、Alchemy RPC、ENS 親名登録、World Portal の app_id / action / RP key、Gemini API key） |
| シード | `scripts/seed.py` でデモ用 Agent 3 件・Human Task 2 件・レビューを投入できる |

### 準備手順（README に記載する。ユーザー作業）

1. Sepolia ETH を用意し、サーバー署名用ウォレットに送る
2. ENSv2 Sepolia で親名 **`choice.eth`**（決定済み。Agent は `<label>.choice.eth`）を登録（MockUSDC を mint → `ens register commit/reveal --chain sepolia`、または提供するスクリプト）
3. World Developer Portal でアプリ作成、RP 登録、action 3 つ作成、`app_id` / `rp_id` / `RP_SIGNING_KEY` を取得
4. Gemini API key を取得
5. Foundry で Escrow / MockUSDC をデプロイし、アドレスを `.env` に設定

### ディレクトリ構成（予定）

```
apps/web/            Next.js
  app/(marketplace|agents|cases|jury|tasks|me)/...
  lib/(api|wagmi|ens|world).ts
apps/api/            FastAPI
  app/(main.py|db|models|schemas|routers|services|agents|chain)
  alembic/
  scripts/seed.py
contracts/           Foundry (src/Escrow.sol, src/MockUSDC.sol, test/, script/Deploy.s.sol)
docs/specs/, docs/database/（database-design スキルで生成）
```

## 検証基準

すべてローカル（`docker compose up` + `apps/api` + `apps/web`）と Sepolia で実際に操作して確認する。

- [ ] V1. ウォレット接続 → SIWE 署名 → ログイン状態になり、アドレス（または ENS 名）がヘッダーに表示される
- [ ] V2. PM Agent を作成し「公開する」と、Sepolia ENSv2 に `<label>.<parent>.eth` が発行され、`getEnsText(name, "description")` で登録した説明が返る
- [ ] V3. マーケットプレイスに公開済み Agent がカテゴリ・評価付きで並び、詳細ページで ENS レコードが表示される
- [ ] V4. 案件を作成すると PM Agent がタスク（AI タスクと Human Task を含む）とチーム案を生成し、承認画面に出る
- [ ] V5. 「承認して入金」で MockUSDC が Escrow に入り、案件が `in_progress` になる（Etherscan で `Deposited` を確認）
- [ ] V6. AI タスクが自動で完了し、成果物が案件ボードに表示される
- [ ] V7. Human Task 一覧に案件由来のタスクが出て、World ID 検証を経て受注・提出でき、案件側で `done` になる
- [ ] V8. 全タスク完了後、「承認して支払う」で Escrow から配分どおり送金され、案件が `completed` になる
- [ ] V9. World ID 検証を経てレビューを投稿でき、Agent 詳細に「人間確認済み」バッジ付きで表示され、ENS の `agent.rating` が更新される
- [ ] V10. 同じ World ID で同じ案件に 2 回レビューしようとすると拒否される
- [ ] V11. 「差し戻す」と論点サマリーが生成され、Jury 画面に紛争が出る。当事者は投票できない
- [ ] V12. 第三者 3 名が World ID 検証のうえ投票すると、多数決結果どおり Escrow が `resolve` され、案件が `resolved` になる
- [ ] V13. Foundry テストが全件成功する
- [ ] V14. `scripts/seed.py` でデモ用データを投入し、上記を初見の人が README の手順で再現できる

## 未決事項

- ENSv2 Sepolia ベータの Registry `register` の正確なシグネチャ・roleBitmap 定数は実装時に `ensdomains/ens-cli` および deployments ページで確認する。ベータ仕様変更で書き込みが不安定な場合は、読み取りのみ ENS 実データ・書き込みは「ENS 書き込みキュー」として tx 内容を表示するフォールバックを用意する（その場合は仕様書に追記する）
- Python フレームワークは FastAPI を採用（ユーザー回答は LLM=Gemini のみ指定。Django 希望なら変更）

## 決定事項

| 日付 | 内容 |
|---|---|
| 2026-09-25 | ENS 親名は `choice.eth`（Sepolia ENSv2）。Agent は `<label>.choice.eth` として発行する |

## 追補 1（2026-09-25）: 会社の人員を ENS で管理し、PM Agent が Human Task を指名する

### 決定事項

| 項目 | 決定 |
|---|---|
| 人員の所属 | 受注側の会社（人材を提供する側）。発注側の社内担当者は対象外 |
| 名前空間 | 会社が所有する独自の `.eth` の下（例 `dan.field-co.eth`）。subname の発行と record の書き込みは **会社管理者のウォレットが署名**する（API は calldata を用意するだけ） |
| 割り当て | PM Agent が Human Task ごとに候補（ENS レコード）を見て 1 名を指名。本人が World ID で人間確認して受諾。辞退・無応答なら次の候補に再指名。候補ゼロなら従来の公開募集（Human Task Marketplace）に落とす |
| 登録 UI | 「会社と人員」画面。会社管理者が会社（ENS 名）と人員（名前・ウォレット・役割・スキル・拠点・稼働可否）を登録 |

### F9. 会社と人員の登録

- 会社作成: 入力 = 会社名、ENS 名（例 `field-co.eth`）、説明。API は接続ウォレットがその名前の所有者か（ENSv2 `ETHRegistry.getState(labelhash).latestOwner`）を確認する。RPC 未設定時はモックで通す。
- 人員追加: 入力 = 表示名、ラベル（subname）、ウォレット、役割、スキル（カンマ区切り）、拠点、稼働可否。DB に保存し `ens_status=pending`。
- ENS 書き込み: `GET /companies/{id}/members/{mid}/ens-calldata` が `register`（会社のサブレジストリ）と `multicall(setAddr, setText...)`（会社名のリゾルバ）の calldata を返す。フロントが会社管理者のウォレットで順に送信し、tx hash を `POST .../ens-written` で報告 → `ens_status=written`。
- 人員の text record: `person.company`、`person.role`、`person.skills`、`person.location`、`person.available`、`addr`。

### F10. PM Agent による指名

- 案件が `in_progress` になり Human Task が生成されたとき、API が候補（`available=true` の全人員、辞退済みを除く）を集め、Gemini に「タスク内容と候補の ENS レコード」を渡して 1 名と理由を選ばせる（モック時はスキル一致数と評価で決定的に選ぶ）。
- `human_tasks.status = assigned`、`assignee_member_id`、`assignment_reason` を保存。指名された人には通知（ベル）と「あなたへの指名」一覧に出る。
- 受諾: 指名された本人（ウォレット一致）だけが `POST /human-tasks/{id}/accept`（World 検証つき）を呼べる → `accepted`。
- 辞退: `POST /human-tasks/{id}/decline` → `declined_member_ids` に追加し再指名。候補が尽きたら `open`（公開募集）。
- 案件詳細のチーム編成パネルは、Human Task の担当に指名された人員の ENS 名を表示する。

### 検証基準（追加）

- [ ] V15. 会社を ENS 名つきで登録し、人員を 3 名追加すると `/companies` 画面に ENS 名（`<label>.<company>.eth`）つきで並ぶ
- [ ] V16. 案件を入金すると Human Task が自動で 1 名に指名され、指名理由が表示される。指名された本人以外は受諾できない
- [ ] V17. 指名された本人が辞退すると次の候補に再指名され、候補が尽きると公開募集になる

## 追補 2（2026-09-25）: アーキテクチャ設計書への整合

`architecture/architecture.md`（CMP-001〜017、IF-001〜023、ADR-001〜007）に合わせて次を変更した。

| 設計書の要求 | 実装 |
|---|---|
| CON-006 契約・預託はタスク単位 | Escrow を `openCase`（承認者と必要承認数を固定）→ `fundTask`（工程ごとに預託）に変更。PM 管理費も 1 タスクとして契約 |
| ADR-005 成果物はハッシュのみオンチェーン | `submit(caseId, taskId, keccak(成果物), 支払先)`。承認は (ハッシュ, 支払先) に紐づき、再提出で無効化 |
| FR-012 / FR-013 承認がそろうと自動支払い、未達なら保留 | `approve` で承認者の EIP-712 署名を検証し、`approvalCount >= threshold` でコントラクトが送金。オフチェーンから送金を指示する経路は無い |
| FR-019 裁定に基づく資金解放 | `dispute` → `resolve(pay, refund)`（合計 = 預託額）を worker が送信 |
| ADR-006 書き込みはチェーン連携ワーカーに集約 | `chain_jobs`（冪等キー UNIQUE、再送 5 回、単一スレッド）。Escrow と ENS の全書き込みが経由。確定状態を `tasks.chain_status` に投影し、`/cases/{id}/resync` でオンチェーンから取り直せる |
| NFR-001 5 行為の World 検証 | action を `request` / `approve` / `review` / `jury` / `human-task` の 5 つに拡張。依頼開始と各承認で proof を要求 |
| 発注者側の承認者（アクター） | 依頼時に承認者ウォレットと必要数を指定（既定は発注者本人 1 名）。承認者だけが署名できる |
| FR-027 プロジェクト subname | openCase 後に `project-<n>.<agent>.choice.eth` を発行し、`project.case` / `project.escrow` / `project.status` 等を record に書く（Agent ごとにサブレジストリを自動デプロイ） |

### 設計書との残差（意図的に残しているもの）

- 成果物ストレージ（CMP-011）は置かず、実体は DB のテキスト。ハッシュのみオンチェーン。
- サービス層 8 コンポーネントは FastAPI 単一プロセス。ワーカーも同プロセスのスレッド（AQ-006 の選択）。
- イベント購読（IF-017）は tx レシートの取り込みと `resync` による再読で代替。リオルグ対応は無い（AQ-007）。
- 運用ウォレットの鍵は `.env` の平文（AQ-003）。
- Reputation は DB で集計したうえで ENS の text record にも書く（設計書より前に出ている）。
- Human Task の指名（会社人員の ENS 管理）は設計書に無い追加要件（追補 1）。

### 検証基準（更新）

- V5 は「openCase 後、worker が工程ごとに fundTask を送り、全タスクが `funded` になる」に変更
- V8 は「承認者の署名が必要数そろった工程から自動で `paid` になり、全工程が支払われると案件が `completed` になる」に変更
- V18. 1 人目の承認だけでは保留（`submitted` のまま）で、2 人目で自動支払いされる（`scripts/smoke_flow.py`）
- V19. Sepolia 実機で openCase → fundTask → submit → approve → Paid までの tx が確認できる（`scripts/smoke_chain.py`）


## 追補 3（2026-09-26）: ENSv2 EAC による役割分離（ENS プライズ整合）

ETHGlobal Tokyo の ENS プライズ「Best Use of ENSv2」が挙げる階層型レジストリ・EAC・Permissioned Resolver・Agent を名前空間として扱う、の 4 点を実データで示すため、次を実装した。

- **運用鍵を 3 つに分離**: Owner（プロフィールと subname 発行）、Reputation（評価 3 キーのみ）、Project Agent（project subname の発行と `codrea.project.*` のみ）。
- **Agent を名前空間に**: 公開時に Agent 自身のサブレジストリ（UserRegistry）をデプロイし、Project 鍵にそのサブレジストリの `ROLE_REGISTRAR` だけを付与する。
- **役割ごとの subname とリゾルバ**: `reputation.<agent>` は Reputation 鍵が所有し Reputation リゾルバを使う。`project-<n>.<agent>` は Project 鍵が登録し Project リゾルバを使う。共有リゾルバには Owner しか書けない。
- **record キーを `codrea.` 名前空間に統一**（`codrea.agent.*` / `codrea.project.*` / `codrea.person.*`）。
- **検証**: `scripts/ens_roles_check.py` で各鍵の許可・拒否を eth_call で確認。Agent 詳細の権限表はモックを廃し、オンチェーンの `hasRootRoles` を読んで表示する。

制約: デプロイ済みの ENSv2 実装ではリソース単位の `grantRoles` が拒否されるため、キー単位の権限ではなく subname 単位で分離した。Creator 所有の Agent（自分の `.eth` の下）では、この分離は Creator 側の設定に委ねる（未実装）。
