# 手動テスト手順: Creator の収益（D3）と運用ジョブ画面（G1）

> 作成日: 2026-09-26
> 対象: `GET /agents/{id}/earnings`、`/agents/mine` の「収益」、`GET /ops/jobs`、`POST /ops/jobs/{id}/retry`、`/ops/jobs` 画面、`OPS_ADDRESSES`

テストは 2 部構成です。**A はモックモード**（鍵不要、支払いまで数分で通る）で収益の数字と再投入の成功経路を確認し、**B は今の実チェーン設定**で「オンチェーン反映済みなら再送しない」判定と運用者の制限を確認します。

## 0. 前提

- API のコードは変わっているので、**起動中の API（8001）は再起動**してください（`--reload` なしで起動していると新コードが載りません）。
- `apps/api/.env` は現在、実チェーン（Sepolia RPC / ENS 書き込み / World 検証 有効、`DEV_LOGIN_ENABLED=true`）です。A ではこの `.env` を触らず、別ポートに環境変数を直接渡して起動します。
- MetaMask を 1 つ用意します（A ではチェーンは問いません。署名だけ使います）。

---

## A. モックモードで収益と再投入を通す

### A-1. テスト用 DB とモック API（8002）、Web（3001）を起動

```bash
# DB（既存の choice は触らない）
docker compose exec db psql -U choice -d choice -c "drop database if exists choice_test" -c "create database choice_test"

# API（モック。運用者は OPS_ADDRESSES 空 + DEV_LOGIN_ENABLED=true なので全員に開放）
cd apps/api
DATABASE_URL=postgresql+psycopg://choice:choice@localhost:5433/choice_test \
ESCROW_ADDRESS= USDC_ADDRESS= SEPOLIA_RPC_URL= ENS_WRITE_ENABLED=false WORLD_VERIFY_ENABLED=false GEMINI_API_KEY= \
DEV_LOGIN_ENABLED=true OPS_ADDRESSES= CORS_ORIGINS=http://localhost:3001 APP_URL=http://localhost:3001 API_URL=http://localhost:8002 \
.venv/bin/uvicorn app.main:app --port 8002

# Web（別ターミナル。8002 に向けて 3001 で起動）
cd apps/web
NEXT_PUBLIC_API_URL=http://localhost:8002 pnpm dev -p 3001
```

http://localhost:3001 を開き、ヘッダー右上に `mock: chain, ens_write, world, gemini` が出ていることを確認します。

### A-2. Agent を公開する（Creator = MetaMask）

1. 「Sign in」で MetaMask の SIWE 署名。
2. 「Agent 管理」→「＋ 新しい PM Agent」。名前 `テスト PM`、ラベル `test-pm`、公開先はプラットフォーム（`choice.eth`）、利用料 5%、他は任意 →作成→「ENS に公開」。
3. **確認**: 一覧に `test-pm.choice.eth` と状態「公開中」。カードに **「収益」ボタン**がある。
4. 「収益」を押す。**期待**: 「受取済 0 USDC」「預託中（未払い） 0」「案件 0 件 · 利用料 5.0%」と、「まだ PM 管理費の預託はありません」の文言。

### A-3. 案件 1（支払いまで通す。同じ MetaMask が発注者・承認者）

1. Marketplace で `テスト PM` →「依頼」。内容「レストラン予約サイトを作りたい」、予算 `300`、承認者は既定（自分 1 名）→「内容を確認して依頼を開始」（World はモックで通る）。
2. 案件詳細で計画が出たら「承認して預託」系のボタン（`Escrow.openCase に署名…` と表示。モックなので即完了）。
3. 進捗を待つ（AI 工程が順に done → 「PM 管理（タスク分解・チーム編成・進捗管理）」も提出済になる。数十秒）。
4. Agent 管理 →「収益」。**期待**: 案件 1 行、状態「預託済」または「提出済（承認待ち）」、PM 管理費 = 予算 − 各工程の合計（例 300 USDC の 5% 前後）、**受取額 0**、上部「預託中（未払い）」にその額。
5. 案件詳細の PM 管理工程で「承認」（MetaMask で EIP-712 署名。デモログインでは承認できない旨が出るので必ずウォレットで）。
6. Agent 管理 →「収益」。**期待**: その行が「支払済」、受取額 = PM 管理費、上部「受取済」に加算、tx は `0xmock…`（リンクなし）。
7. マイページ「受取履歴」にも同じ工程が出ないことを確認（受取先が自分のアドレスなら出ます。Agent の受取先 = 自分なので **出るのが正しい**。金額が一致することを確認）。

### A-4. 案件 2（差し戻し → 返金。収益に数えないことを確認）

1. 同じ Agent にもう 1 件依頼（予算 `100`）。openCase → AI 工程が提出済になるまで待つ。
2. 案件詳細で「差し戻す」（理由は任意）。紛争が作られ、状態「紛争中」。
3. **別のブラウザ（またはシークレットウィンドウ）**で http://localhost:3001 を開き、ヘッダーの「デモログイン」→ `Jury 1` → 「Jury」→ 該当紛争 → **「返金」に投票**（World はモック）。`Jury 2`、`Jury 3` でも同様に「返金」。
4. 3 票目で裁定。案件が「仲裁で解決」になる。
5. 元のブラウザで Agent 管理 →「収益」。**期待**: 案件 2 の行が「裁定済」、**受取額 0（返金）**、上部「受取済」は案件 1 の額のまま、「裁定で受取」は表示されない（0 のため）。案件 2 の PM 管理費は「預託中」にも含まれない。

### A-5. 運用ジョブ画面（一覧・フィルタ）

1. デモログイン `運用者`（または今の MetaMask のまま。モックでは全員に開放）。ナビに **「運用」** が出る。
2. `/ops/jobs`。**期待**: 「ワーカー 稼働中」、状態ボタンに件数（確定 = ここまでの fund_task / submit / approve / dispute / resolve / ens_publish / ens_project の合計）、一覧の各行に種類のラベル、対象（案件名 / 工程名 / Agent 名）、金額、試行 `1 / 5`、tx `0xmock…`。
3. 状態ボタン「確定」を押す → 確定だけに絞れる。もう一度押すと解除。種類のプルダウンで `fund_task` を選ぶ → 預託ジョブだけになる。
4. 案件名のリンクを押す → 監査ビューに飛ぶ。Agent 名のリンク → Agent 詳細。

### A-6. 再投入（成功経路、状態の制約、順序）

`chain_jobs` を直接いじって失敗ジョブを作ります。

```bash
# 一番古い fund_task を failed（5 回失敗）にする
docker compose exec db psql -U choice -d choice_test -c \
 "update chain_jobs set status='failed', attempts=5, error='手動テスト: 疑似失敗' where id=(select id from chain_jobs where kind='fund_task' order by created_at limit 1)"
```

1. `/ops/jobs` を 5 秒待つか再読み込み。**期待**: 「失敗 1」、その行が**一覧の先頭**（最古のジョブでも先頭に来る）、エラー欄に「手動テスト: 疑似失敗」、行末に **「再投入」** ボタン。
2. 「再投入」を押す。**期待**: 行が「再送待ち」→ 数秒で「確定」、試行 `1 / 5`、エラー欄末尾に `[運用者が再投入 …]`、tx が新しい `0xmock…` に変わる。
3. 確定行には「再投入」ボタンが無いことを確認。
4. 再送待ちのジョブは再投入できないことを確認:
   ```bash
   docker compose exec db psql -U choice -d choice_test -c \
    "update chain_jobs set status='retry', next_attempt_at=now()+interval '10 minutes' where id=(select id from chain_jobs where kind='submit' order by created_at limit 1)"
   ```
   一覧に「再送待ち」で出るが**「再投入」ボタンは出ない**（ワーカーが自動再送する対象）。確認後に戻す:
   ```bash
   docker compose exec db psql -U choice -d choice_test -c "update chain_jobs set status='done', next_attempt_at=null where status='retry'"
   ```
5. 順序の確認（limit より古い失敗が消えない）: 一覧の URL は変えられないので API で確認します。
   ```bash
   TOKEN=$(curl -s -X POST localhost:8002/auth/dev-login -H 'content-type: application/json' -d '{"role":"ops"}' | python3 -c 'import sys,json;print(json.load(sys.stdin)["token"])')
   docker compose exec db psql -U choice -d choice_test -c "update chain_jobs set status='failed', attempts=5 where id=(select id from chain_jobs order by created_at limit 1)"
   curl -s "localhost:8002/ops/jobs?limit=3" -H "authorization: Bearer $TOKEN" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["counts"]);print([j["status"] for j in d["jobs"]])'
   ```
   **期待**: `counts` の failed が 1 で、3 件しか返さなくても先頭が `failed`。終わったら画面から「再投入」で確定に戻す。

### A-7. ENS 公開ジョブの再投入（Agent の状態が戻る）

```bash
docker compose exec db psql -U choice -d choice_test -c \
 "update chain_jobs set status='failed', attempts=5, error='手動テスト' where kind='ens_publish'; update agents set status='publish_failed', ens_error='手動テスト' where label='test-pm'"
```

1. Agent 管理で `テスト PM` が「公開失敗」になっていることを確認。
2. `/ops/jobs` で該当行（Agent 名 `テスト PM`）を「再投入」。**期待**: ジョブが確定、Agent 管理で「公開中」に戻り、エラー文言が消える。

### A-8. 権限（運用者以外）

1. デモログイン `発注者` に切り替える。**期待**: モックでは `OPS_ADDRESSES` が空なので「運用」は出たままで使える（仕様どおり）。
2. 8002 の API を `OPS_ADDRESSES=0x326ed9de89268ca616980229228bc3208faeb9a3`（デモログイン「運用者」の固定アドレス）を付けて再起動。
3. 発注者のまま `/ops/jobs` を直接開く。**期待**: ナビに「運用」が無く、画面は「この画面は運用者（API の OPS_ADDRESSES に登録したウォレット）だけが使えます」。`curl -H "authorization: Bearer <発注者のトークン>" localhost:8002/ops/jobs` は 403。
4. デモログイン `運用者` に切り替える。**期待**: 「運用」が出て一覧が見える。

A が終わったら 8002 と 3001 を止めます。

---

## B. 実チェーン設定（今の `.env`）で反映済み判定と制限を確認

`apps/api/.env` の 8001 を新コードで再起動し、http://localhost:3000 で行います。ローカル DB `choice` には **fund_task の失敗ジョブが 1 件**残っています。

### B-1. 運用画面の表示

1. MetaMask で Sign in（`DEV_LOGIN_ENABLED=true` かつ `OPS_ADDRESSES` 未設定なので全員に開放）。ナビ「運用」→ `/ops/jobs`。
2. **期待**: 「失敗 1」で fund_task の行が先頭。対象の案件名、金額、tx リンク（Etherscan）、エラー本文が見える。

### B-2. 反映済み判定（再送しない）

1. 失敗行の案件リンクから監査ビューを開き、その工程の状態を控える。
2. `/ops/jobs` で「再投入」。
   - オンチェーンで既に **預託済（funded 以降）** なら **期待**: エラーボックスに「オンチェーンの工程は既に funded です（…）再送せず、案件詳細の「再同期」で…」（409）。行の状態は「失敗」のまま。案件詳細の「再同期」を押すと投影が `funded` に直る。
   - 本当に未預託なら **期待**: 「再送待ち」→「確定」となり、Etherscan で新しい `fundTask` の tx が見える。
3. どちらになったかを記録してください（実機では前者が起きるのが、この修正の狙いです）。

### B-3. ENS 更新ジョブの再投入（実 tx が 1 本出る。ガス少額）

```bash
docker compose exec db psql -U choice -d choice -c \
 "update chain_jobs set status='failed', attempts=5, error='手動テスト' where id=(select id from chain_jobs where kind='ens_update' order by created_at desc limit 1)"
```

「再投入」→ **期待**: 確定になり tx が新しい Etherscan リンクに変わる。ENS 画面でその Agent の record が変わっていない（同じ値を書き直しただけ）ことを確認。

### B-4. 運用者の制限

1. `.env` に `OPS_ADDRESSES=<自分の MetaMask アドレス>` を追加して 8001 を再起動。
2. 自分の MetaMask で Sign in → 「運用」が出る。
3. デモログイン `発注者` に切り替え → 「運用」が消え、`/ops/jobs` 直打ちで案内文。`/ops/jobs` API は 403。
4. `OPS_ADDRESSES` を空に戻す場合は再起動を忘れずに。

### B-5. 収益（実データ）

ローカル DB には支払い済みの PM 管理工程がまだ無いので、実チェーンで A-3 と同じ流れ（実ウォレットで openCase → PM 工程を承認）を 1 件通すと「支払済」と Etherscan の tx リンクが出ます。時間が無ければ A の結果で代替してください。

---

## 確認結果の記録欄

| 項目 | 結果 | メモ |
|---|---|---|
| A-2 収益 0 表示 | | |
| A-3 預託中 → 支払済 | | |
| A-4 返金は受取額 0、合計に入らない | | |
| A-5 一覧・フィルタ・リンク | | |
| A-6 失敗が先頭、再投入で確定、再送待ちは不可 | | |
| A-7 ENS 公開の再投入で Agent が公開中に戻る | | |
| A-8 OPS_ADDRESSES で制限 | | |
| B-2 反映済みなら 409 | | 実際の結果: |
| B-3 ENS 更新の再投入 | | tx: |
| B-4 制限 | | |
