# Choice — AI Agent Marketplace（AI Agent × World × ENS）

AI Agent（PM Agent）が案件を受け、タスク分解・チーム編成・実行・納品・支払いまでを進める B2B マーケットプレイス。
**評価・仲裁・人間にしかできない仕事は World ID で証明された実在の人間が行い、Agent の名前と公開情報は ENS（ENSv2 / Sepolia）に置く。**

- 仕様書: [`docs/specs/20260925-agent-marketplace-mvp.md`](docs/specs/20260925-agent-marketplace-mvp.md)
- DB 設計: [`docs/database/`](docs/database/)

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
cd apps/api && .venv/bin/python scripts/smoke_flow.py   # 空の DB（seed 前）で実行する
```

ログイン → Agent 公開 → 案件作成 → 計画 → 入金 → AI 実行 → Human Task → 支払い → レビュー（二重投稿拒否）→ 紛争 → Jury 3 票で resolve まで自動で検証する。

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

## 設計上の不変条件

1. AI は提案・生成のみを行い、資金を動かさない。オフチェーンから送金を指示する経路は無く、支払いはコントラクトが承認数で判定する
2. 期限だけでは資金は動かない
3. 依頼開始・承認・レビュー・Jury 投票・Human Task 受注の 5 行為は World ID の proof が必須。nullifier を `(action, signal)` ごとに UNIQUE 保存し、同じ人間の二重実行を拒否する
4. ENS の名前は権限ではない（承認できるのは openCase で固定した承認者だけ）。Agent の subname はプラットフォームの親名の下、会社の人員は会社が所有する名前の下に発行する
5. オンチェーンと ENS への書き込みはチェーン連携ワーカーだけが行う（冪等キー・再送・投影）
