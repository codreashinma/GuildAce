---
name: dev-implementation-architecture-analysis
description: リポジトリの現在の実装（apps/api の FastAPI・apps/web の Next.js・contracts の Solidity・デプロイ設定）を読み、実際に動いているアーキテクチャ（コンポーネント・インターフェース・データの置き場所・外部連携・横断的関心事・デプロイ構成）をコードから復元する。dev-architecture-design が出力した設計書（docs/architecture/architecture.md）の CMP / IF / ADR と突き合わせて、設計とのずれ（未実装・設計外の実装・食い違い）を洗い出し、現状アーキテクチャ解析書と設計差分レポートを Markdown で、現状の構成図を SVG で /mnt/c/second-brain/ethglobal_hackathon/docs/as-built に作成・更新する。ユーザーが「現実装のアーキテクチャを解析して」「今のコードの構成を図にして」「実装と設計のずれを洗い出して」「as-built を作って」「コードからアーキテクチャを起こして」「設計どおりに実装できているか確認して」と言ったときに使う。これから作るものを設計するのは dev-architecture-design。
---

# dev-implementation-architecture-analysis

**いま動いているコードが、実際にどういう構成になっているか**を、コードだけを根拠にして書き起こすスキル。あわせて、設計書とどこがずれているかを示す。

`dev-architecture-design` が「こう作るべき」を決めるのに対して、このスキルは「実際にこうなっている」を記録する。**両者を混ぜない。**

- **コードに書かれていることだけを書く。** 設計書・README・コミットメッセージ・コメントに「〜する」と書いてあっても、コードで確かめられなければ事実として扱わない（「コメントでは〜と書かれているが、実装は確認できない」と書く）。
- **記述にはすべて根拠を付ける。** 根拠はファイルパスと行番号で示す（`apps/api/app/services/worker.py:42`）。根拠を付けられない記述は書かない。
- **コードも設計書も直さない。** このスキルは読むだけ。ずれを見つけても、どちらを直すかは決めずに差分レポートに載せ、判断をユーザーに委ねる（5 章）。
- 推測で埋めない。読み切れなかった範囲は「未解析」と明記する。

## 0. 作業ディレクトリ

```bash
REPO=/home/million/team_codrea_ethglocal          # 解析対象（読み取りのみ）
DOCS_DIR=/mnt/c/second-brain/ethglobal_hackathon/docs
OUT=$DOCS_DIR/as-built                            # 出力先
```

- **読み取るのはリポジトリ、書き込むのは `$OUT` だけ**。リポジトリ内の `docs/` には書かない。リポジトリのファイルは 1 行も変更しない。
- 突き合わせに使う設計資料: `$DOCS_DIR/architecture/`（とくに `architecture.md` / `architecture-decisions.md`）、`$DOCS_DIR/database/database-design.md`、`$DOCS_DIR/agent-infra/agent-infra.md`。
- `$DOCS_DIR` は Obsidian の vault（Windows 側 `C:\second-brain`）を WSL からマウントしたもの。
  - `.obsidian/` 配下と `*:Zone.Identifier` は読まない。
  - 改行は LF、文字コードは UTF-8。見出し・テーブル・Mermaid は標準の Markdown 記法に収める。
- 解析対象から外すもの: `node_modules/` `.next/` `.venv/` `__pycache__/` `contracts/lib/`（forge-std / OpenZeppelin は外部ライブラリ）`contracts/out/` `contracts/cache/` `contracts/broadcast/` `.demo-template-*` `apps/web/public/`。
  - `contracts/lib/` は**中身を解析しない**が、「どのライブラリのどの機能に依存しているか」（`import` 文）は記録する。
- **秘密情報を出力に書き写さない。** `.env` / `.env.local` は開かない。環境変数は `.env.example` と `config.py` の**変数名だけ**を扱い、値は書かない。コードに鍵やトークンらしき文字列が直書きされていたら、値を伏せたうえで「秘密情報の直書き」としてリスクに上げる。
- `$DOCS_DIR` にアクセスできない場合は、勝手に別の場所へ書かず、ユーザーにパスを確認する。

## 1. 解析の範囲と基準を決める

着手前に次を確定し、解析書の「前提」に書く:

1. **基準のコミット**: `git -C $REPO rev-parse --short HEAD` とブランチ名。解析はこのコミット時点のものであることを明記する。
2. **作業ツリーの状態**: `git -C $REPO status --porcelain`。**コミットされていない変更がある場合**、解析に含めるかどうかで結果が変わる。アプリのコード（`apps/` `contracts/`）に未コミットの変更があるときだけ、含めるかどうかを 1 度だけユーザーに確認する。ドキュメントやスキルの変更だけなら確認せず、HEAD の内容で解析する。
3. **既存の出力**: `$OUT/` に前回の解析書があれば読み、前回の基準コミットからの差分（`git diff --stat <前回>..HEAD`）を見て、**変わった範囲を重点的に**解析し直す。

## 2. コードから構成を復元する

次の順で進める。**先に全体の地図（2-1）を作ってから個別を読む。** いきなり個別のファイルを読み込むと、全体の構成を見失う。

各項目で使うコマンドは起点に過ぎない。grep で見つけた箇所は**必ず前後を開いて読み**、呼ばれている側まで追う。grep の件数だけで結論を出さない。

### 2-1. 全体の地図（実行単位を数える）

「別々のプロセスとして動くもの」と「データストア」を列挙する。これが現状のコンテナになる。

```bash
cd $REPO
git ls-files | grep -vE '^contracts/lib/|node_modules|\.demo-template' | sed 's|/[^/]*$||' | sort | uniq -c | sort -rn | head -40
cat docker-compose.yml render.yaml apps/api/Dockerfile apps/web/vercel.json
cat apps/web/package.json apps/api/requirements.txt contracts/foundry.toml
```

- 実行単位ごとに、**起動の入口**（`apps/api/app/main.py` の `app`、`next start`、`Deploy.s.sol` 等）を特定する。
- **同じプロセスの中で動いているバックグラウンド処理**（例: `lifespan` の中で `worker.start()` しているワーカー）は、コードの上では別の責務でも**実行単位としては API と同居している**。設計書で別コンテナになっている場合は、ずれとして記録する。
- データストア（PostgreSQL 等）は `db.py` / `config.py` / `docker-compose.yml` / `render.yaml` から、種類と接続方法を拾う。

### 2-2. バックエンド（apps/api）

| 見るもの | 起点 | 拾うこと |
|---|---|---|
| ルータ | `app/main.py` の `include_router`、`app/routers/*.py` | 公開している HTTP エンドポイントの全量（メソッド・パス・認証の要否・呼んでいるサービス） |
| サービス | `app/services/*.py` | 責務と、どの外部システムに出ていくか |
| モデル | `app/models.py` / `app/schemas.py` | テーブルと、オンチェーン・ENS の値を**複製して持っているか**（投影・キャッシュの有無） |
| 認証 | `app/auth.py` / `routers/auth.py` | 誰が何をしてよいかを、どこで判定しているか |
| 設定 | `app/config.py` / `.env.example` | 機能フラグ（`chain_enabled` 等）と、それで切り替わる経路 |
| 起動処理 | `app/main.py` の `lifespan` | マイグレーションの方式、常駐処理、起動時の警告 |
| スクリプト | `scripts/*.py` | 運用で手で叩く経路（ENS のセットアップ・シード・スモークテスト）。**アプリの経路とは分けて記録する** |

```bash
grep -rnE '@router\.(get|post|put|patch|delete)' apps/api/app/routers | sed 's/:.*@router\./ /'
grep -rnE 'Depends\(' apps/api/app/routers | grep -oE 'Depends\([a-z_]+' | sort | uniq -c
grep -rnE '^from|^import' apps/api/app | grep -E 'services|web3|httpx|genai|siwe|jwt' | sort -u
```

- エンドポイントは全件を表にする（件数が多ければ付録に回す）。**認証が付いていない更新系のエンドポイント**は必ず拾う。
- 呼び出し関係は「ルータ → サービス → 外部」の向きで追う。**サービスがルータを import している**など、向きが逆流している箇所は記録する。

### 2-3. フロントエンド（apps/web）

| 見るもの | 起点 | 拾うこと |
|---|---|---|
| 画面 | `src/app/**/page.tsx` | 画面の全量（ルート）と、どの API を叩き、どの tx を送るか |
| API クライアント | `src/lib/api.ts` | バックエンドとの境界。叩いているパスの全量 |
| チェーン | `src/lib/chain.ts` / `contracts.ts` / `wagmi.ts`、`components/publish-agent.ts` | **ブラウザから直接**送っている tx・読んでいるコントラクト（バックエンドを経由しない経路） |
| 認証 | `src/lib/auth.tsx`、`components/world-verify.tsx` | SIWE・World の検証をどこで行い、何をバックエンドへ送るか |
| モック | `src/lib/mock.ts` / `empty.ts` | **本物の API の代わりにモックが使われる条件**。本番経路とモックの経路を区別して書く |

```bash
find apps/web/src/app -name 'page.tsx' | sed 's|apps/web/src/app||;s|/page.tsx||'
grep -rnoE "(api|fetch)[A-Za-z]*\(['\`\"][^'\`\"]+" apps/web/src | sort -u
grep -rnE 'writeContract|sendTransaction|readContract|useReadContract|useWriteContract|signMessage' apps/web/src
grep -rnE 'NEXT_PUBLIC_[A-Z_]+' -o apps/web/src | sort -u
```

- **フロントが叩いているパス**と、**バックエンドが公開しているパス**を突き合わせる。片方にしか無いもの（呼ばれていないエンドポイント、存在しないパスへの呼び出し）は記録する。
- `NEXT_PUBLIC_` の環境変数はブラウザに露出する。秘密情報に当たるものが混ざっていないか確かめる。

### 2-4. コントラクト（contracts）

| 見るもの | 拾うこと |
|---|---|
| `src/Escrow.sol` | 状態（enum / struct / mapping）、状態遷移の関数と**誰が呼べるか**（modifier / require）、event の全量、資金が外へ出る箇所 |
| `src/MockUSDC.sol` | テスト用トークンであること。本番で何に差し替わる想定か（コードで確かめられる範囲） |
| `script/Deploy.s.sol` | デプロイの手順、初期化で設定する権限（owner・resolver 等） |
| `test/Escrow.t.sol` | テストで**確かめている不変条件**（テストがあることと、その性質が保証されていることは別。テストの範囲をそのまま書く） |

```bash
grep -nE '^\s*(function|event|modifier|enum|struct|error)\s' contracts/src/*.sol
grep -nE 'onlyOwner|msg\.sender|require\(|revert ' contracts/src/Escrow.sol
grep -rnE 'transfer\(|transferFrom\(|safeTransfer' contracts/src
```

- **オフチェーン側がこのコントラクトをどう使っているか**を、ABI の使用箇所から逆引きする（`apps/api/app/services/chain.py`、`apps/web/src/lib/contracts.ts`）。どの関数を API が呼び、どれをブラウザが呼ぶかを分けて書く。
- **どの鍵で署名しているか**（サーバが持つ運営鍵か、利用者のウォレットか）は、資金の安全性に直結するので必ず特定する。

### 2-5. 外部連携

外部システムごとに、**入口になっているファイル**・方式・認証・失敗時の挙動を拾う。

| 外部システム | 主な入口 |
|---|---|
| World（人間性の証明） | `apps/api/app/services/world.py`、`routers/world.py`、`apps/web/src/components/world-verify.tsx` |
| ENS | `apps/api/app/services/ens.py`、`routers/ens.py`、`apps/api/scripts/ens_*.py`、`apps/web/src/components/ens-*.tsx` |
| チェーン（Escrow） | `apps/api/app/services/chain.py` / `worker.py`、`apps/web/src/lib/chain.ts` |
| LLM（Gemini） | `apps/api/app/services/gemini.py` |
| 決済（x402） | `apps/web/package.json` の `@x402/*` と、その使用箇所 |

```bash
grep -rnE 'https?://[a-zA-Z0-9.-]+' -o apps/api/app apps/web/src | sort -u
grep -rnE 'timeout|retry|except|catch' apps/api/app/services | wc -l
```

- 表の入口は **2026-09-26 時点**のもの。実際にはこの表を鵜呑みにせず、grep で入口を確かめ直す。表に無い外部連携が見つかったら追加する。
- **依存しているだけで使っていない**パッケージ（`package.json` / `requirements.txt` にあるが import されていない）は、連携として数えずに別枠で記録する。
- 外部が落ちたときに**何が止まり、何が動くか**を、例外処理とフラグ（`chain_enabled` 等）から読み取る。

### 2-6. データの置き場所

データごとに、**実装上の正本がどこにあるか**を決める。判断はコードの書き込み経路で行う:

- DB にだけ書かれる → DB が正本
- チェーン / ENS に書いてから DB に写す（ワーカーによる投影・キャッシュ） → チェーン / ENS が正本、DB は複製
- **両方に独立に書いている** → 正本が 2 つある。**不整合のリスクとして必ず記録する**

投影を再構築する手段（イベントからの再同期処理）がコードにあるかどうかも確かめる。

### 2-7. 横断的関心事

`dev-architecture-design` の 10 章と同じ観点で、**実装がどうなっているか**を拾う。実装が無いものは「実装なし」と書く（設計書に方針があっても、コードに無ければ無い）。

| 関心事 | 見る場所の例 |
|---|---|
| 認証・認可 | `auth.py` の依存関数がどのエンドポイントに付いているか、JWT の署名鍵と有効期限、`dev_login_enabled` のような**抜け道** |
| 監査ログ | tx の記録（`case_audit.py`）、`logging` の出力先 |
| 通知 | `components/notifications.tsx` と、その元データ |
| エラー処理・リトライ・冪等性 | ワーカーの再試行、tx の nonce 管理、同じ要求が 2 回来たときの扱い（ユニーク制約・状態チェック） |
| 秘密情報の管理 | 鍵・トークンを読む箇所（`config.py`）と、ログやレスポンスに漏れていないか |
| 障害時の縮退 | 外部呼び出しの例外処理、機能フラグで経路を切り替える箇所 |
| マイグレーション | `create_all` と手書きの `_migrate()` の範囲。**スキーマの変更履歴が残らない**ことはリスクとして書く |

### 2-8. デプロイ構成

`render.yaml` / `apps/api/Dockerfile` / `apps/web/vercel.json` / `docker-compose.yml` / `contracts/script/Deploy.s.sol` / `README.md` のデプロイ手順から、**どの実行環境に何が載っているか**・環境変数の受け渡し・ネットワークの境界（CORS の許可元を含む）を拾う。ローカル開発（docker-compose）と公開環境（Vercel / Render / テストネット）は分けて書く。

## 3. 設計書と突き合わせる

`$DOCS_DIR/architecture/architecture.md` の CMP / IF / ADR（必要に応じて `database-design.md` のテーブル・イベント）を、2 章で復元した構成と 1 件ずつ対応づける。

### 3-1. 対応づけのルール

- **設計書の ID を使う。** 現状の要素が設計書のどの CMP / IF に当たるかを決め、同じ ID で呼ぶ。新しい ID 系列でコンポーネントを採番し直さない。
- 設計書に無い要素（設計外の実装）には、仮の ID `X-001` から採番する。次回の解析でも同じ要素には同じ `X-` ID を使う（前回の解析書を読んで引き継ぐ）。
- コード中のコメントに設計の ID（`ADR-006` など）が書かれていれば対応づけの手がかりにするが、**コメントだけで対応を確定しない**。挙動が設計どおりかは中身で確かめる。
  ```bash
  grep -rnoE '\b(CMP|IF|ADR|FR|NFR|UC|CON)-[0-9]{3}\b' apps contracts/src contracts/script --include=*.py --include=*.ts --include=*.tsx --include=*.sol
  ```

### 3-2. ずれの分類

見つかったずれに `DR-001` から採番し、次の 4 つに分類する:

| 分類 | 意味 | 例 |
|---|---|---|
| 未実装 | 設計にあるが、コードに無い | 設計の IF に当たる呼び出しがどこにも無い |
| 設計外 | コードにあるが、設計に無い | 設計に無いエンドポイント・外部連携・データの複製 |
| 食い違い | 両方にあるが、中身が違う | 同期/非同期、呼び出しの向き、認証方式、正本の置き場所、同居/分離 |
| 簡略化 | MVP として意図的に省いたことがコードやコメントから読み取れる | `create_all` でマイグレーションを代用 |

各ずれには次を書く:

- 設計側の根拠（`architecture.md` の章・ID）と、実装側の根拠（`ファイル:行`）
- **影響**: どの要件（とくに NFR）が満たせなくなるか。影響の大きさを `高` / `中` / `低` で付ける。**NFR-003（資金が条件を満たすまでコントラクトの外へ出ない）・NFR-001（人間の行為は World の証明を経る）・NFR-011（個人識別情報を持たない）に関わるものは `高` から下げない**
- **どちらに寄せるかは書かない**。「設計を実装に合わせて直す」「実装を設計に合わせて直す」のどちらもあり得る旨だけを書き、判断はユーザーに委ねる

## 4. 出力する

**解析書は Markdown（`.md`）、構成図は SVG（`.svg`）** で作る。

```bash
mkdir -p "$OUT/img"
```

| ファイル | 内容 |
|---|---|
| `$OUT/as-built-architecture.md` | 現状アーキテクチャ解析書（図はここにインラインで埋め込む） |
| `$OUT/design-drift.md` | 設計との差分レポート |
| `$OUT/img/*.svg` | 現状の構成図 |

既存のファイルがあれば読み、**上書きではなく差分更新**とし、変更履歴に基準コミットとともに追記する。前回あったずれが解消されていれば、行を消さずに状態を「解消（<コミット>）」にする。

### 4-1. `as-built-architecture.md`

```markdown
# 現状アーキテクチャ解析書（as-built）

> 基準コミット: <short sha>（<ブランチ>）
> 未コミットの変更: 含む / 含まない
> 突き合わせた設計書: architecture.md（最終更新 YYYY-MM-DD）
> 最終更新: YYYY-MM-DD

## 1. 概要
- 現状の構成を 1 段落で。**設計書との大きなずれを 3 つまで**先頭に書く（詳細は design-drift.md）
- 解析した範囲 / 解析していない範囲

## 2. 前提
| 項目 | 内容 |
基準コミット、除外したディレクトリ、読めなかったもの

## 3. 実行単位（コンテナ）
### 3-1. 現状のコンテナ図
（`img/01-as-built-container.svg` を埋め込み）
### 3-2. 実行単位の一覧
| 対応ID（CMP / X） | 名称 | 起動の入口 | 技術 | 同居しているもの | 根拠 |

## 4. コンポーネント
| 対応ID | 名称 | 実装の場所 | 実際の責務（何を入力に何を出すか） | 根拠 |

## 5. インターフェース
| 対応ID（IF / X） | 呼び出し元 → 呼び出し先 | 同期/非同期 | 方式 | 認証 | 根拠 |
（呼び出しの向きに循環があるかどうかを 1 行書く）

### 5-1. HTTP エンドポイント
| メソッド | パス | 認証 | 呼ぶサービス | 呼んでいる画面 | 根拠 |
（件数が多ければ付録へ）

### 5-2. コントラクトの呼び出し
| 関数 / event | 呼び出し元（API の運営鍵 / ブラウザのウォレット / ワーカーの購読） | 根拠 |

## 6. 外部連携
| 外部システム | 入口 | 方式 | 認証 | 失敗したとき | 根拠 |
（依存しているだけで使っていないパッケージは別表）

## 7. データの置き場所
| データ | 実装上の正本 | 複製（投影・キャッシュ） | 同期の方法 | 再構築の手段 | 根拠 |

## 8. 主要フロー
Mermaid のシーケンス図で 2〜4 本。**実装を追って書く**（設計書のフローを写さない）。各フローの冒頭に、追ったエントリポイントを書く

## 9. 横断的関心事
| 関心事 | 実装 | 根拠 | 設計との差分（DR-ID） |

## 10. デプロイ構成
（`img/02-as-built-deployment.svg` を埋め込み）
| 環境 | 載るもの | 設定の出どころ | 根拠 |

## 11. リスク
コードから読み取れる構造上のリスク。**バグ探しではない**（個別の不具合は code-review の範囲）
| ID（AR-X01〜） | リスク | 根拠 | 関連する要件 |

## 12. 未解析の範囲
| 範囲 | 理由 |

## 13. 変更履歴
| 日付 | 基準コミット | 内容 |
```

### 4-2. `design-drift.md`

```markdown
# 設計との差分レポート

> 基準コミット: <short sha> / 設計書: architecture.md（最終更新 YYYY-MM-DD）
> 最終更新: YYYY-MM-DD

## サマリ
| 分類 | 件数 | うち影響「高」 |
（未実装 / 設計外 / 食い違い / 簡略化）

## 設計 ID ごとの実装状況
| 設計ID | 名称 | 実装状況（実装済 / 一部 / 未実装 / 形を変えて実装） | 実装の場所 | DR-ID |
CMP と IF は全件を載せる。**実装済みのものも省かない**（埋まっていない行が価値を持つ表なので、全体が見えている必要がある）

## ずれの一覧
### DR-001 <要約>
- **分類**: 未実装 / 設計外 / 食い違い / 簡略化
- **影響**: 高 / 中 / 低（関わる要件 ID）
- **設計**: <architecture.md の章・ID と、書かれていること>
- **実装**: <ファイル:行 と、実際の挙動>
- **状態**: 未対応 / 解消（<コミット>）

## ADR の実装状況
| ADR-ID | 決定 | 実装で守られているか | 根拠 |
```

### 4-3. 構成図（SVG）

| ファイル | 図 | 作らなくてよい場合 |
|---|---|---|
| `01-as-built-container.svg` | 現状の実行単位・データストア・外部システムと、その間の通信 | **必ず作る** |
| `02-as-built-deployment.svg` | 公開環境（Vercel / Render / テストネット等）に何が載っているか | 実行環境の配置がコンテナ図と同じ絵になる場合 |
| `03-as-built-<主題>.svg` | 資金の流れ・署名鍵の所在など、表では伝わりにくい構造 | 表で足りる場合 |

**記法・レイアウト・SVG の書き方・埋め込み方は `dev-architecture-design` スキルの 3-4 に従う**（`.claude/skills/dev-architecture-design/SKILL.md` を読んでから描く）。加えて、このスキル固有の規則:

- **ずれを図に描き込む。** 設計どおりの要素は通常の線、設計外の要素（`X-`）は**橙の枠**、設計にあるが未実装の要素は**灰色の破線の枠**で描き、凡例に意味を書く。
- 各要素に対応 ID（`CMP-` / `IF-` / `X-`）を書き、解析書の表と一致させる。
- **人間でないものを棒人間で描かない。** World・ENS・Escrow コントラクト・LLM・AI エージェントは角丸の箱とステレオタイプ（`&#171;system&#187;` / `&#171;AI agent&#187;`）で描く。棒人間は人間の利用者（発注者 / 発注者側の承認者 / 受注者 / Creator / Human Jury）だけに使う。
- **同じプロセスに同居しているもの**（API とワーカー等）は、1 つの実行単位の枠の中に並べて描く。設計書で別コンテナなら、それ自体がずれなので `DR-` ID を添える。
- 線には、実装で確かめた方式を書く（`HTTPS+JSON / JWT`、`eth_sendRawTransaction / 運営鍵` など）。

## 5. 検証と報告

出力前に自己点検する:

- [ ] **すべての記述に根拠（`ファイル:行`）が付いているか**。根拠の行を実際に開き、書いた内容と合っているか抜き取りで確かめたか
- [ ] 設計書・コメント・README にしか書かれていないことを、事実として書いていないか
- [ ] `main.py` の `include_router` にあるルータのエンドポイントを全件拾ったか（grep の件数と表の行数が一致するか）
- [ ] `src/app/**/page.tsx` の画面を全件拾ったか
- [ ] `Escrow.sol` の external / public 関数と event を全件拾ったか
- [ ] フロントが叩くパスとバックエンドのパスを突き合わせたか
- [ ] 設計書の CMP / IF を**全件** `design-drift.md` の実装状況の表に載せたか
      （`grep -oE '\b(CMP|IF)-[0-9]{3}\b' $DOCS_DIR/architecture/architecture.md | sort -u` と表の ID が一致するか）
- [ ] `DR` / `X` の ID が重複していないか、前回の解析書の ID を振り直していないか
- [ ] NFR-001 / NFR-003 / NFR-011 に関わるずれの影響を「高」にしたか
- [ ] **秘密情報の値を書き写していないか**（`.env` を開いていないか、鍵・トークン・接続文字列の値が出力に無いか）
- [ ] リポジトリのファイルを変更していないか（`git -C $REPO status --porcelain` が着手前と同じか）
- [ ] 保存先が `$OUT/` で、SVG が `$OUT/img/` にあるか（`ls $OUT/*.svg` が空か）
- [ ] 作った SVG がすべて解析書にインラインで埋め込まれ、`.svg` ファイルと内容が一致しているか
- [ ] **SVG が well-formed か**（`xmllint --noout $OUT/img/*.svg`。無ければ `python3 -c "import xml.etree.ElementTree as E;E.parse('<path>')"`）
- [ ] **埋め込んだ SVG に空行が無いか**（`python3 -c "import re,sys;t=open(sys.argv[1]).read();print(sum(1 for b in re.findall(r'<svg .*?</svg>',t,re.S) if re.search(r'\n\s*\n',b)))" <md>` が 0 か）。空行があると Markdown で図が途中で切れて表示されない
- [ ] 棒人間が人間の利用者だけか
- [ ] Mermaid の構文が正しいか（`npx -y @mermaid-js/mermaid-cli` でレンダリングできればする。できなければ目視で確かめ、未検証だと報告する）

最後にユーザーへ短く報告する:

- 作成・更新したファイル（**フルパス**）と、基準コミット
- 実行単位の数・コンポーネント数・インターフェース数・HTTP エンドポイント数
- **設計 ID の実装状況**（CMP / IF それぞれ、全何件中、実装済・一部・未実装が何件か）
- **影響「高」のずれ**を箇条書きで（DR-ID・1 行の要約・根拠のファイル）
- 未解析のまま残した範囲

## 6. 後続への引き渡し

ずれへの対応はこのスキルでは行わない。ユーザーに次を提案する（実行は求められたときだけ）:

- **設計を実装に合わせる場合** → `dev-architecture-design` で `architecture.md` を差分更新する（`DR-` ID を変更履歴に書く）。データの置き場所がずれていれば `dev-database-design`、デプロイ構成なら `dev-agent-infra-design`
- **実装を設計に合わせる場合** → `github-tasks` で `DR-` 単位のタスクにして Project に登録する
- 個別の不具合やセキュリティ上の問題を見つけた場合は、このレポートで深追いせず、`code-review` / `security-review` での確認を提案する
