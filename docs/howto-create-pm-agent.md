# PM Agent の作成手順（Agent 実装担当者向け）

> 作成日: 2026-09-26
> 対象: PM Agent を作って公開し、自分が実装した Agent のロジック（タスク分解・指名・成果物生成）を動かして確認したい人

## 1. PM Agent とは何がどこに保存されるか

PM Agent は「名前・説明・カテゴリ・利用料・進め方（system prompt）・受取アドレス」を持つレコードです。作成すると DB の `agents` に `draft` で保存され、「公開」すると ENS（Sepolia ENSv2）に `<ラベル>.choice.eth` の subname が発行され、プロフィールが text record に書かれます。案件が来ると、Agent の「進め方・ルール」をシステムプロンプトにして Gemini がタスク分解を行います。

| 項目 | 保存先 | 使われ方 |
|---|---|---|
| 名前・説明・カテゴリ・利用料 | `agents` と ENS text record（`description` / `codrea.agent.category` / `codrea.agent.fee_bps`） | Marketplace の一覧・検索・詳細 |
| 進め方・ルール（`rules`） | `agents.rules`（ENS には書かない） | Gemini のシステムプロンプト。タスク分解、Human Task の指名、成果物生成、提出物の確認に渡る |
| 受取アドレス | `agents.payout_address` と ENS `addr` | PM 管理費の支払先（Escrow の payee） |
| 評価・件数・完了数 | `reputation.<ラベル>.choice.eth` の record | レビュー投稿と案件完了で Reputation 鍵が更新 |

## 2. 前提

- **どの環境か**を決める。ローカルのモック（`GEMINI_API_KEY` や RPC が空）なら鍵不要で数秒で公開できるが、計画は固定パターンになる。Gemini を通した分解を見たいなら `apps/api/.env` に `GEMINI_API_KEY` を入れる（ENS や Sepolia は空のままでよい。ENS 公開だけモックになる）。
- ヘッダー右上の `mock: …` に何がモックか出る。`gemini` が出ていれば計画はモック。
- ログインはウォレット（SIWE）か、`DEV_LOGIN_ENABLED=true` のときのデモログイン「Agent 作成者」。Agent の作成・公開だけならどちらでもよい。

## 3. 画面から作る（いちばん簡単）

1. 「Agent 管理」→「＋ 新しい PM Agent」（`/agents/new`）。
2. 入力する。

| 項目 | 何を入れるか | 制約 |
|---|---|---|
| 名前 | 表示名。例「Web開発 PM Agent」 | 1〜120 文字 |
| 公開先（ENS の親名） | 既定はプラットフォームの `choice.eth`。自分の `.eth` の下に置く場合だけ入力（ウォレットで署名が必要。開発中は既定のままでよい） | 所有している `.eth` |
| ENS ラベル | subname のスラッグ。例 `web-pm` → `web-pm.choice.eth` | 英小文字・数字・ハイフン、63 文字まで、同じ親名の下で一意 |
| 説明 | Marketplace に出る紹介文 | 任意 |
| カテゴリ | `web` / `design` / `video` / `wedding` / `other` | 1 つ |
| 利用料（%） | PM 管理費。案件予算からこの割合を PM 工程として預託し、承認で Creator の受取アドレスへ支払う | 0〜50 |
| 進め方・ルール | **Agent の system prompt**。タスクの切り方、人間に任せる仕事、成果物の形式、担当者の選び方など | 自由文 |
| 受取アドレス | 空なら自分のウォレット | 0x アドレス |

3. 「作成」→ 一覧に「下書き」で並ぶ →「ENS に公開」。
4. 状態が「ENS に公開中」→「公開中」になれば完了。モックなら数秒、実チェーンなら 1〜2 分（Agent 本体、専門 Agent 4 件、reputation subname を発行する）。「公開失敗」ならカード下のエラー文を見て「ENS に公開」で再試行。運用者なら `/ops/jobs` からも再投入できる。
5. 「Marketplace」に並ぶこと、Agent 詳細で ENS レコードと権限表が出ることを確認する。

## 4. API・スクリプトから作る（繰り返し試すとき）

ログイン後のトークンを `Authorization: Bearer` に付ける。

```bash
API=http://localhost:8001
# デモログインでトークンを取る（DEV_LOGIN_ENABLED=true のとき）
TOKEN=$(curl -s -X POST $API/auth/dev-login -H 'content-type: application/json' -d '{"role":"creator"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')

# 作成（draft）
AGENT=$(curl -s -X POST $API/agents -H "authorization: Bearer $TOKEN" -H 'content-type: application/json' -d '{
  "name": "Web開発 PM Agent",
  "label": "web-pm-test",
  "description": "Web サービスの MVP を短期間で。",
  "category": "web",
  "fee_bps": 500,
  "rules": "1. 案件を 4〜6 タスクに分解する 2. デザイン→フロント→バックエンド→QA の順 3. 現地確認や実物レビューは Human Task にする 4. 成果物は Markdown"
}')
ID=$(echo $AGENT | python3 -c 'import sys,json;print(json.load(sys.stdin)["id"])')

# 公開（platform: ワーカーが ENS に発行。モックなら即 published）
curl -s -X POST $API/agents/$ID/publish -H "authorization: Bearer $TOKEN"
# 状態確認
curl -s $API/agents/$ID | python3 -c 'import sys,json;a=json.load(sys.stdin);print(a["status"], a["ens_name"], a.get("ens_error"))'
```

- `fee_bps` は bps（100 = 1%）。画面の「利用料（%）」と単位が違う。
- ラベルが重複すると 409。
- 更新は `PATCH /agents/{id}`（`description` / `rules` / `fee_bps`）。公開済みなら ENS レコードも書き直される。
- まとめて作るなら `apps/api/scripts/seed.py` の `AGENTS` 配列に追記して `.venv/bin/python scripts/seed.py http://localhost:8001`。同じラベルは飛ばされる。

## 5. 「進め方・ルール」が Agent の挙動をどう決めるか

すべて `apps/api/app/services/gemini.py`。`GEMINI_API_KEY` が空ならモック関数が同じ形の値を返す。

| 場面 | 関数 | Agent の `rules` の使われ方 | 出力の形 |
|---|---|---|---|
| 案件作成直後の計画 | `plan_case` | システムプロンプトに「あなたは PM Agent『名前』です。以下は作成者が定めた進め方・ルールです」として埋め込む | `tasks[]`（3〜6 件。`title` / `description` / `type: ai\|human` / `role: designer\|frontend\|backend\|qa\|field\|pm` / `estimated_cost`）と `team[]`、`summary`。合計が「予算 −（予算 × 利用料）」を超えると最大 3 回再生成 |
| 預託後の AI 工程 | `execute_ai_task` | 同じくシステムプロンプト | Markdown の成果物 |
| Human Task の指名 | `assign_human_task` | 同上。候補（ENS レコード: 役割・スキル・拠点・稼働可否）から 1 名と理由 | `member_id` と `reason` |
| Human Task の提出確認 | `check_human_submission` | 使わない（タスクの完成条件と提出物だけ） | `meets_requirements` と `comment` |
| 差し戻し時の論点整理 | `summarize_dispute` | 使わない | 争点・双方の主張・確認事項 |

ルールを書くときのコツ:

- 「タスクは 4〜6 個」「順番」「Human Task にする条件」「成果物の形式」を明示すると計画が安定する。
- `type=human` のタスクが 1 つ以上出るようにしないと、指名・Human Task の経路が動かない。
- 各タスクの `estimated_cost` は USDC の整数。0 のタスクは Escrow が `ZeroAmount` で拒否するので、ルールで「各タスク 1 USDC 以上」と書いておく（プランナー側の検証は未実装）。
- PM 管理費は Agent 側が自動で 1 工程として追加する（`cases.py` の `PM_FEE_TITLE`）。ルールで PM 工程を作らせない。

## 6. 作った Agent で動作確認する

1. 別のユーザー（デモログイン「発注者」か別ウォレット）で Marketplace から Agent を開き「依頼」。内容・予算・納期を入れて「依頼を開始」（World はモックなら自動で通る）。
2. 案件詳細（`/cases/{id}`）に計画が出る。ここが `plan_case` の結果。JSON そのものは `GET /cases/{id}` の `plan_json`。
3. 計画が気に入らなければ「条件を見直して再計画する」（`POST /cases/{id}/replan`）でルールを直しながら繰り返せる。ルールの変更は「Agent 管理」→「編集」（`PATCH /agents/{id}`）。
4. 「承認して預託」（モックなら即時）→ AI 工程が順に実行され、成果物が積み上がる。Human Task は「Human Task」画面に指名付きで出る。
5. 通しで壊れていないかは `scripts/smoke_flow.py`（モックモードの API に対して実行）で確認できる。

## 7. よくあるつまずき

| 症状 | 原因と対処 |
|---|---|
| 「〜は既に使われています」(409) | 同じ親名の下に同じラベルがある。ラベルを変えるか、「Agent 管理」で既存を使う |
| 公開失敗 | エラー文を見る。実チェーンなら運用鍵の Sepolia ETH 不足か RPC の制限が多い。「ENS に公開」で再試行、または運用者が `/ops/jobs` から再投入 |
| 計画がいつも同じ | `mock: gemini` が出ている。`GEMINI_API_KEY` を入れて API を再起動 |
| 計画失敗（planning_failed） | 予算内に収まらなかったか JSON が壊れた。`GET /cases/{id}` の `error` を見る。予算を上げるかルールで金額の目安を書く |
| 承認できない | デモログインのユーザーは EIP-712 署名ができない。承認者はウォレットで Sign in する |
| Human Task が指名されない | 会社と人員（`/companies`）に稼働可能な人員が無い。無ければ公開募集になる |

関連: 仕様書 `docs/specs/20260925-agent-marketplace-mvp.md`（F2 / F4 / F10）、API 一覧 `docs/apis.csv`（API-12〜17）。
