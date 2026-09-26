# Choice — AI Agent Marketplace（AI Agent × World × ENS）

AI Agent（PM Agent）が案件を受け、タスク分解・チーム編成・実行・納品・支払いまでを進める B2B マーケットプレイス。
**評価・仲裁・人間にしかできない仕事は World ID で証明された実在の人間が行い、Agent の名前と公開情報は ENS（ENSv2 / Sepolia）に置く。**

- 仕様書: [`docs/specs/20260925-agent-marketplace-mvp.md`](docs/specs/20260925-agent-marketplace-mvp.md)
- DB 設計: [`docs/database/`](docs/database/)
- AI 利用開示（提出用）: [`docs/ai-disclosure.md`](docs/ai-disclosure.md) / 主要プロンプト: [`docs/ai-prompts.md`](docs/ai-prompts.md)

## 構成

| ディレクトリ | 内容 |
|---|---|
| `apps/web` | Next.js 16 / wagmi + RainbowKit（SIWE ログイン）/ `@worldcoin/idkit` v4 |
| `apps/api` | FastAPI / SQLAlchemy / Gemini（PM Agent の頭脳: タスク分解・Human Task の指名・論点整理）/ web3.py（ENSv2・Escrow）|
| `contracts` | Foundry: `Escrow.sol`（タスク単位: openCase / fundTask / submit / approve(EIP-712, 自動支払い) / dispute / resolve）と `MockUSDC.sol` |
| `docker-compose.yml` | PostgreSQL 16（ポート 5433） |

外部連携（Sepolia / ENS 書き込み / World ID / Gemini）は **未設定ならモックで動く**ので、鍵なしで全フローを試せる。ヘッダー右上に `mock: ...` と出ているものがモック。

## ローカルで動かす（モック）

```bash
# 1. DB
docker compose up -d db

# 2. API（http://localhost:8001）
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8001 --reload

# 3. デモデータ（別ターミナル）
.venv/bin/python scripts/seed.py

# 4. Web（http://localhost:3000）
cd ../web
pnpm install
cp .env.example .env.local
pnpm dev
```

MetaMask 等で Sepolia に接続 → 「Sign in」で SIWE 署名 → Marketplace から案件を作成。ウォレットが無ければヘッダーの「デモログイン」で役割を選んで試せる。

### バックエンドの通しテスト

```bash
# 別の DB（choice_test）に向けたモックモードの API を起動してから実行する
docker compose exec db psql -U choice -d choice -c "create database choice_test"
cd apps/api
DATABASE_URL=postgresql+psycopg://choice:choice@localhost:5433/choice_test ESCROW_ADDRESS= USDC_ADDRESS= SEPOLIA_RPC_URL= ENS_WRITE_ENABLED=false \
  .venv/bin/uvicorn app.main:app --port 8002
.venv/bin/python scripts/smoke_flow.py http://localhost:8002   # 2 回目以降は choice_test を作り直す
```

ログイン → Agent 公開 → 案件作成 → 計画 → 入金 → AI 実行 → Human Task → 支払い → レビュー（二重投稿拒否）→ 紛争 → Jury 3 票で resolve まで自動で検証する。

### デモ用データ（モックモード）

`scripts/seed.py` は Agent 3 件と、Web PM Agent の案件を 3 件（支払い済み・Jury で返金・進行中）作る。デモログインが有効なら Agent の作成者は「Agent 作成者」ロールになるので、デモログイン → 「Agent 管理」→「収益」で受取済・預託中・返金（受取 0）の並びが見られる。運用画面（`/ops/jobs`）用の失敗ジョブと再送待ちジョブは、API と同じ `DATABASE_URL` を渡して `scripts/seed_ops.py` を実行すると作れる（冪等。`[demo]` 付きのエラー文で見分ける）。

```bash
.venv/bin/python scripts/seed.py http://localhost:8001
DATABASE_URL=postgresql+psycopg://choice:choice@localhost:5433/choice .venv/bin/python scripts/seed_ops.py
```

### コントラクトのテスト

```bash
cd contracts && forge test
```

## 本物の Sepolia / ENS / World / Gemini につなぐ

1. **サーバー署名者**: ウォレットを 1 つ用意し、Sepolia ETH を入れる。秘密鍵を `apps/api/.env` の `SERVER_PRIVATE_KEY` に。RPC を `SEPOLIA_RPC_URL` に。
2. **Escrow / MockUSDC をデプロイ**
   ```bash
   cd contracts
   OPS_ADDRESS=<サーバー署名者のアドレス> forge script script/Deploy.s.sol --rpc-url $SEPOLIA_RPC_URL --broadcast --private-key $DEPLOYER_PRIVATE_KEY
   ```
   出力の `Escrow` / `MockUSDC` を `.env` の `ESCROW_ADDRESS` / `USDC_ADDRESS` に。
3. **ENSv2（Sepolia beta）**: 親名 `choice.eth` を登録し、リゾルバとサブレジストリを用意する（1 回だけ）。
   ```bash
   cd apps/api && .venv/bin/python scripts/ens_setup.py
   ```
   出力された `ENS_OWNED_RESOLVER` / `ENS_PARENT_SUBREGISTRY` を `.env` に書き、`ENS_WRITE_ENABLED=true`。
   以降、Agent を公開すると `<label>.choice.eth` が発行され、text record（description / agent.category / agent.fee_bps / agent.rating / agent.completed …）が書かれる。
4. **World ID**: [Developer Portal](https://developer.world.org) でアプリと RP を作り、action `review` / `jury` / `human-task` を作成。`WORLD_APP_ID` / `WORLD_RP_ID` / `WORLD_RP_SIGNING_KEY` を設定し `WORLD_VERIFY_ENABLED=true`。
5. **Gemini**: `GEMINI_API_KEY` を設定（モデルは `GEMINI_MODEL`、既定 `gemini-2.5-flash`）。

## Agent の公開先（ENS）

Agent 作成時に公開先を選べる。

- **プラットフォームの親名**（既定）: `<label>.choice.eth`。運用ウォレット（チェーン連携ワーカー）が subname を発行し record を書く。
- **Creator 自身の ENS 名**: `<label>.<creator>.eth`。接続ウォレットがその名前の所有者かを ENSv2 で確認し、API は Creator が署名する calldata だけを返す（鍵は使わない）。名前にサブレジストリとリゾルバが無い場合は、作成画面の事前確認に「自分のウォレットでリゾルバとサブレジストリを用意する」が出る（`/ens/setup-calldata`）。公開時は platform と同じ名前空間を Creator 側の鍵で構築する（最大 11 tx）:
  1. `register` と `multicall`（プロフィール）
  2. Agent 自身のサブレジストリ（UserRegistry、root = Creator）をデプロイして `setSubregistry`
  3. プラットフォームの Project 鍵に `grantRootRoles(ROLE_REGISTRAR)`（EAC: この Agent の下で project subname を発行することだけを許す）
  4. `reputation.<label>.<creator>.eth` を Reputation 鍵の所有・Reputation リゾルバで発行（評価はこの鍵だけが書ける）
  5. 専門 AI エージェント（designer / frontend / backend / qa）の subname と record（任意）

  `ens-written` の受領時にサブレジストリ・権限・reputation をオンチェーンで確認し、評価 record の初期値を Reputation 鍵で書く。以降、評価・完了数は platform と同じく `reputation.<agent>` に反映され、案件の project subname も Project 鍵が Creator のサブレジストリに発行する。プロフィールの編集（`/agents/[id]/edit`）は Creator が `multicall` に署名する。実機確認は `scripts/smoke_creator.py`。

## ENS の読み取りと確認（`/ens/*`）

- `GET /ens/resolve?name=` … `.eth` レジストリ → サブレジストリ → リゾルバと辿って所有者・レジストリ・リゾルバ・addr・text record を返す。同時に、見つけたリゾルバへ ENSIP-10 の `resolve(bytes name, bytes data)` を投げ、直読みと同じ値が返るかを `wildcard` として同梱する（Sepolia の UniversalResolver `0xeEeE…EeEe` は現時点で v2 名を見つけられないため、直読みが正、ENSIP-10 は整合確認）。
- `GET /ens/readiness?name=` / `GET /ens/check-owner?name=` … Creator 所有の Agent や会社の人員を発行する前提（登録済み・サブレジストリ・リゾルバ・所有者一致）を入力中に確認する。
- `GET /ens/register-calldata?name=&phase=commit|register` … 利用者が自分のウォレットで `.eth`（2LD）を登録する calldata。commit（テスト用トークンの mint / approve 込み）→ 60 秒 → register。Agent 作成と会社登録の事前確認で「未登録」なら登録ボタンが出て、登録 → リゾルバとサブレジストリの準備まで続けて署名できる。
- `GET /ens/setup-calldata?name=` … 名前の所有者が自分のウォレットで OwnedResolver と UserRegistry を用意する calldata（CREATE2 の予定アドレス付き）。運用者の鍵は使わない。
- `GET /ens/reverse?address=` … 発行済みの名前（人員 / Agent 受取 / 会社管理者）からの逆引き。承認者・Jury・レビュー投稿者を名前で表示する。
- `GET /ens/names` … 発行した全名前（Agent・専門 subagent・reputation・案件 project・人員）と tx。画面は `/ens`。
- `GET /cases/{id}/audit` … 案件ごとの tx（openCase / fund / submit / approve / pay / dispute / resolve）と ENS 発行を時系列に並べ、発注者・承認者・支払先・Jury のアドレスを `/ens/reverse` と同じ規則で ENS 名にして返す（監査ビュー `/cases/[id]/audit`、認証不要。署名や nullifier は返さない）。
- `GET /me/summary` … ログイン中のウォレットに紐づく ENS 名（人員 / Agent 受取 / 会社管理者）、World ID で人間確認した行為の回数、所属会社、作成した Agent、関わった案件数、受取履歴（Escrow が自分へ支払った工程）。画面は `/me`（ヘッダー「マイページ」）。
- 所有確認は「未登録」「RPC エラー」を拒否し、RPC 未設定（モック）のときだけ確認なしで通す。利用者が送った ENS 書き込み tx は自己申告の hash を信用せず、レシートと text record をオンチェーンで確認してから `published` / `written` にする。
- 役割鍵（Reputation / Project）が未設定で Owner 鍵にフォールバックしているときは `/config` の `mock.ens_roles=true` になり、ヘッダーに `mock: ens_roles` と出る。

## 会社の人員と Human Task の指名

受注側の会社は、自社が所有する `.eth` の下に人員を subname として登録する（例 `dan.field-co.eth`、record: `person.role` / `person.skills` / `person.location` / `person.available`）。
subname 発行と record 書き込みは会社管理者のウォレットが署名する（API は calldata を返すだけ）。
案件の Human Task が生まれると PM Agent が候補の ENS レコードを見て 1 名を指名し、本人が World で人間確認して受諾する。辞退なら次の候補、候補ゼロなら Human Task Marketplace で公開募集になる。

## 資金の流れ（アーキテクチャ設計書 ADR-001 / ADR-005 / ADR-006 準拠）

1. 発注者が `Escrow.openCase` で承認者と必要承認数を固定し、USDC の引き落としを許可する
2. チェーン連携ワーカーが工程（タスク）ごとに `fundTask` で預託する。PM 管理費も 1 工程
3. 成果物が提出されると `submit(成果物ハッシュ, 支払先)` を送る。実体はオフチェーン、ハッシュだけがオンチェーン
4. 承認者は World で人間確認をし、(ハッシュ, 支払先) に EIP-712 で署名する。ワーカーが `approve` を中継し、必要数がそろった工程からコントラクトが自動で支払う
5. 差し戻しは `dispute` で保留。Jury の多数決を `resolve` で反映する

Sepolia 実機の通しテスト: `cd apps/api && .venv/bin/python scripts/smoke_chain.py`

## 公開環境（2026-09-26）

| 役割 | URL | 備考 |
|---|---|---|
| Web | https://choice-dun.vercel.app | Vercel プロジェクト `choice`（`apps/web`）。`choice-codrea.vercel.app` はチーム SSO 保護付きなので使わない |
| API | https://choice-api-rcr5.onrender.com | Render Web Service `choice-api`（Docker、Free、Singapore）。Free はアイドルで停止するため審査前に `/health` を叩いて起こす |
| DB | Render PostgreSQL 16 `choice-db`（Free、Singapore） | ローカルのデモデータを復元済み。Free は 30 日で失効 |

- Render はチームのリポジトリ（プライベート）を取得できないため、ミラー `codreashinma/team_codrea_ethglocal` からデプロイしている。反映は `git push deploy feature/agent-marketplace-mvp`（`deploy` リモート）。
- Web の再デプロイは `cd apps/web && vercel --prod`。API の URL は Vercel の環境変数 `NEXT_PUBLIC_API_URL`。
- API の環境変数は Render のダッシュボード（`DATABASE_URL` は外部接続 + `sslmode=require`、`CORS_ORIGINS` / `APP_URL` = Web の URL、`DEV_LOGIN_ENABLED=false`）。

## デモ・公開前チェックリスト

- `JWT_SECRET` をランダムな値にする（既定値のままだと API 起動時に警告が出る）
- `DEV_LOGIN_ENABLED=false` にする。デモログインのユーザーは秘密鍵が無いので、実チェーンでは openCase と EIP-712 承認ができない（画面にもその旨が出る）。発注者・承認者・Human Task 受注者は実ウォレットで Sign in する
- World を実連携にする（`WORLD_APP_ID` / `WORLD_RP_ID` / `WORLD_RP_SIGNING_KEY`、`WORLD_VERIFY_ENABLED=true`）。モックのときはボタンに「（World モック）」、ヘッダーに `mock: world` と出る
- `GEMINI_API_KEY` を設定する。空だと固定の計画と「（モック）」入りの成果物になる
- 公開 URL に出すなら `NEXT_PUBLIC_API_URL`（https）、API の `CORS_ORIGINS` / `APP_URL` / `API_URL` に公開 origin を入れる。ENS の `url` / `codrea.agent.endpoint` / `codrea.project.url` に書かれるため、変更後は `scripts/ens_rewrite_urls.py` で既存 Agent の record を書き直す（`docs/ens-manual-check.md` 8 章）
- ウォレットが Sepolia 以外に接続されている場合は、書き込み・署名の前に自動で切替を促す
- 運用者のウォレットを `OPS_ADDRESSES`（カンマ区切り）に入れると、ナビに「運用」が出て `/ops/jobs` でチェーン連携ジョブ（Escrow / ENS への全書き込み）の状態確認と、5 回失敗したジョブの再投入ができる。未設定のときは `DEV_LOGIN_ENABLED=true` のローカルでのみ全員に開放

## 設計上の不変条件

1. AI は提案・生成のみを行い、資金を動かさない。オフチェーンから送金を指示する経路は無く、支払いはコントラクトが承認数で判定する
2. 期限だけでは資金は動かない
3. 依頼開始・承認・レビュー・Jury 投票・Human Task 受注の 5 行為は World ID の proof が必須。nullifier を `(action, signal)` ごとに UNIQUE 保存し、同じ人間の二重実行を拒否する
4. ENS の名前は権限ではない（承認できるのは openCase で固定した承認者だけ）。Agent の subname はプラットフォームの親名の下、会社の人員は会社が所有する名前の下に発行する
5. オンチェーンと ENS への書き込みはチェーン連携ワーカーだけが行う（冪等キー・再送・投影）
