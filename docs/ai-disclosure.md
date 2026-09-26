# AI 利用開示（ETHGlobal Tokyo 提出用）

> 作成日: 2026-09-26
> 対象: GuildAce — Digital Company Marketplace（AI Agent × World × ENS）
> 関連: [重要プロンプト集](ai-prompts.md) / [仕様書](specs/20260925-agent-marketplace-mvp.md) / [DB 設計](database/) / [ENS 実機確認手順と記録](ens-manual-check.md)

この文書は、本プロジェクトの開発における生成 AI の利用内容と、人間が担当した判断・確認・テスト・修正を開示するものです。
本文書自体も Claude Code で下書きし、人間（ENS 担当）が内容を確認して提出します。

---

## 1. 使用した AI ツール

| 区分 | ツール | 用途 |
|---|---|---|
| 開発支援 | **Claude Code**（Anthropic 製 CLI エージェント）。モデルは **Claude Fable 5.1** | 仕様書・DB 設計書の作成、コード実装、テスト作成、ドキュメント、デモ資料、デプロイ作業の補助 |
| 開発支援（Claude Code 内のスキル） | `dialogue-dev`（対話で仕様化してから実装する社内フロー）、`database-design`（リポジトリ同梱 `.claude/skills/database-design`）、`github-tasks`（同 `.claude/skills/github-tasks`）、`pdf`、`pptx`、`claude-in-chrome`（ブラウザ操作による動作確認） | 下記 2 章参照 |
| 開発支援（サブエージェント） | Claude Code の general-purpose サブエージェント（計 7 回） | プロジェクトレビュー、ENS プライズ要件との照合、コード探索 |
| **製品機能としての AI**（開発ツールではない） | Google **Gemini**（既定モデル `gemini-2.5-flash`、`apps/api/app/services/gemini.py`） | PM Agent の頭脳。案件のタスク分解・チーム編成、Human Task の担当者指名、紛争時の論点整理、AI タスクの成果物生成。**資金移動の判断は行わない**（README「設計上の不変条件」1） |

補足:

- 画像生成 AI は使用していません。リポジトリ内の画像（`docs/*.svg`、`apps/web/public/*.svg`）は人間作成のアーキテクチャ図と Next.js の初期アセットです。
- コードレビュー系の外部 AI サービス（Copilot、CodeRabbit 等）は使用していません。
- チームメンバーごとの利用状況は 7 章に記載しています。

---

## 2. AI を利用したファイル・機能

Git 履歴で確認できる範囲では、コミット 57 件のうち 41 件に `Co-Authored-By: Claude Fable 5.1` のトレーラーが付いています（ENS 担当のコミットは、マージコミットと `.gitignore` 編集を除きすべて Claude Code と共同で作成）。

| 領域 | 対象 | AI の関与 | 人間の関与（詳細は 4〜6 章） |
|---|---|---|---|
| 仕様 | `docs/specs/20260925-agent-marketplace-mvp.md` | コンセプト図 3 枚・ユースケース PDF・アーキテクチャ図をもとに、`dialogue-dev` スキルで要件を質問しながら Claude が起草。追補 1〜3 も Claude が起草 | 親名 `choice.eth`、スコープ、人員の ENS 管理、EAC による役割分離などの**決定はすべて人間**。追補は人間の指示（プロンプト集 P-04, P-07, P-14）を反映 |
| DB 設計 | `docs/database/database-design.md`、`er-diagram.md`、`revision-prompt-A.md` | 別の Claude セッションで人間が作成させた設計書を、本セッションの Claude が実装と照合して矛盾 7 件を指摘。人間の指示で**修正プロンプト**（`revision-prompt-A.md`）を作成しリポジトリに収録 | 矛盾の扱い（承認者集合のオンチェーン固定、Human Task を工程として預託 等）は人間が採否を判断 |
| スマートコントラクト | `contracts/src/Escrow.sol`、`MockUSDC.sol`、`contracts/test/Escrow.t.sol`（10 テスト）、`script/Deploy.s.sol` | Claude が実装・テストを作成。アーキテクチャ設計書（ADR-001/005/006、FR-012/013）に合わせた「タスク単位の預託・EIP-712 承認・閾値到達で自動支払い」への改修も Claude が実施 | 「アーキテクチャに揃える」の判断、Sepolia へのデプロイと資金投入、Etherscan での tx 確認は人間 |
| API（FastAPI） | `apps/api/app/`（ルーター 13、サービス 7）、`apps/api/scripts/`（10 本） | Claude が実装。ENSv2 レジストリ直読み、EAC 役割分離、チェーン連携ワーカー（`chain_jobs`）、World ID 検証、Gemini 連携、SIWE、モックモード | 設計判断・実機検証は人間（4 章、5 章） |
| Web（Next.js） | `apps/web/src/`（ページ 16、コンポーネント 13） | Claude が実装。Marketplace / Agent 作成・公開 / 案件ボード / Human Task / Jury / 会社と人員 / ENS 画面 / 監査ビュー / マイページ | UI 方針（白黒・改行禁止）、必要画面と優先度（`docs/screens.csv` の C1/D1/A2）は人間が決定 |
| ENS 実機確認 | `docs/ens-manual-check.md`、`scripts/ens_setup.py`、`ens_check.py`、`ens_roles_check.py`、`ens_rewrite_urls.py` | Claude が手順書と確認スクリプトを作成 | Sepolia 上で `choice.eth` の登録、Agent 公開、各鍵の許可・拒否の確認、公開 URL への record 書き直しを人間が実行 |
| 画面・API 一覧 | `docs/screens.csv`、`docs/apis.csv` | Claude が洗い出し | 優先度の決定と着手順は人間 |
| README・デプロイ | `README.md`、`render.yaml`、`apps/api/Dockerfile`、Vercel 設定 | Claude が起草・作成 | Vercel / Render のログイン、環境変数の投入、ミラーリポジトリの運用は人間 |
| デモ資料 | `deliverables/ethglobal-demo-template-20260926/*.pptx`、`発表ガイド.md` | Claude が `pptx` スキルでテンプレートを生成 | 差し替え欄（チーム名、デモ内容、証拠、URL）は人間が記入。デモ動画の構成案（プロンプト集 P-27）は人間が作成し、Claude は実装状況との照合のみ |
| チーム共有資料 | `docs/20260926-実装状況メモ.pdf`（`.gitignore` 対象） | Claude が `pdf` スキルで作成 | 共有先・内容の取捨は人間 |

### AI の具体的な用途（要件チェック項目別）

| 用途 | 内容 |
|---|---|
| 設計 | 仕様書、DB 設計書の照合と改訂プロンプト、ENS 名前空間設計（`<label>.choice.eth` / `reputation.*` / `project-<n>.*` / `<role>.*`）、Escrow の状態遷移、画面・API 一覧 |
| コード | 上記のコントラクト、API、Web、スクリプトの実装。既存機能の改修（例: ラベル一意性を ENS 名単位に変更、Multicall3 による RPC 削減、nonce 競合の修正） |
| テスト | Foundry テスト 10 件、モックモードの通しテスト `scripts/smoke_flow.py`（V1〜V18 相当を自動検証）、Sepolia 実機テスト `scripts/smoke_chain.py`、Creator フロー `scripts/smoke_creator.py`、権限確認 `scripts/ens_roles_check.py` |
| 文章 | README、手順書、コミットメッセージ、PR 説明、本開示文書の下書き |
| 画像 | **不使用** |
| 運用補助 | ブラウザ操作での動作確認（`claude-in-chrome`）、Vercel / Render CLI の実行、Git のブランチ統合手順の提案 |

---

## 3. 開発の進め方（仕様駆動）

1. **コンセプト提示（人間）**: 2026-09-25 19:49 JST、コンセプト図 3 枚と「このプロダクトつくるよー」から開始。参照資料として `docs/ETH_Globalユースケース.pdf`、`docs/01-アーキテクチャ図.svg`、要件メモ（FR-001〜034）、アーキテクチャ設計書（CMP/IF/ADR）を人間が用意。
2. **仕様化（AI が質問、人間が回答）**: `dialogue-dev` スキルで Claude が未決事項（親名、LLM、フレームワーク等）を質問し、人間が回答。回答は仕様書の「決定事項」「未決事項」に記録。
3. **実装（AI）→ 確認（人間）**: 機能単位でコミット。人間がローカルと Sepolia で操作し、問題を指摘して修正を依頼（5 章）。
4. **設計書との整合（人間の指示）**: 人間がアーキテクチャ設計書との相違確認を指示し、「アーキテクチャに揃える」と決定。Claude が差分表を作り、仕様書「追補 2」に整合内容と**意図的に残した残差**を記録。
5. **プライズ要件との整合（人間の指示）**: 人間が ENS プライズページとの照合を指示。Claude の提案から人間が着手順を選択し、仕様書「追補 3」に実装内容と制約（リソース単位 `grantRoles` が拒否されるため subname 単位で分離）を記録。

リポジトリに収録している仕様・計画・プロンプト:

| 種別 | 場所 |
|---|---|
| 仕様書（追補 1〜3 を含む） | `docs/specs/20260925-agent-marketplace-mvp.md` |
| DB 設計書・ER 図 | `docs/database/database-design.md`、`docs/database/er-diagram.md` |
| AI への修正プロンプト（原文） | `docs/database/revision-prompt-A.md` |
| 画面・API の計画 | `docs/screens.csv`、`docs/apis.csv` |
| 開発で使った主要プロンプト（時系列。目的・プロンプト・結果。セッション記録をもとに読みやすく編集） | `docs/ai-prompts.md` |
| AI への常設指示（スキル定義） | `.claude/skills/database-design/SKILL.md`、`.claude/skills/github-tasks/SKILL.md` |
| 実機確認手順と記録 | `docs/ens-manual-check.md` |

---

## 4. 人間が担当した設計判断

| 判断 | 内容 | 根拠となる指示 |
|---|---|---|
| プロダクトの方向 | 「AI が案件を進め、評価・仲裁・人間にしかできない仕事は World ID 検証済みの人間が行い、Agent の名前と公開情報は ENS に置く」というコンセプト図を人間が作成 | P-01 |
| ENS 親名 | `choice.eth`（Sepolia ENSv2） | P-02 |
| 人員管理 | 受注側の会社の人員を会社所有の `.eth` の下で ENS 管理し、Human Task の担当者指名を PM Agent の役割にする | P-04 |
| アーキテクチャ準拠 | 設計書（ADR-001/005/006 等）に実装を揃える。Escrow をタスク単位の預託・EIP-712 承認・自動支払いに変更 | P-06, P-07 |
| UI 方針 | 白黒のシンプルな UI、途中改行の禁止 | P-08 |
| DB 設計の是正 | 矛盾 7 件の修正方針を採用し、修正プロンプトとして記録 | P-10, P-11 |
| 画面・API の優先順位 | 必要画面一覧から C1（承認待ち一覧）・D1（公開先選択）・A2（指名通知）を先行 | P-12, P-13 |
| ENS プライズ整合 | 階層型レジストリ・EAC・Permissioned Resolver・Agent を名前空間とする 4 点を実データで示す。着手順（1 → 3）を人間が選択 | P-14 |
| ラベルの一意性 | ラベルの一意性を DB 全体ではなく ENS 名（label + 親名）の単位に変更 | P-18 |
| 任意の `.eth` 登録 | 利用者が自分のウォレットで 2LD を登録できる画面を追加 | P-19 |
| 公開環境 | Vercel（Web）と Render（API / DB）で公開、Render 用ミラーリポジトリの運用 | P-20 |
| ブランチ統合 | 他の開発者が派生させたブランチがある状況での master 統合手順を決定、PR #1 / #2 をレビューして承認 | P-26 |
| 残すモック | 契約条件の文言、openCase 前の project subname の予測表示、検収期限の仮計算の 3 つは表示補助として残す（仕様書 追補 3-2） | 人間の確認のうえ記録 |

---

## 5. 人間が担当した確認・テスト・修正

### 5-1. 実機・ブラウザでの確認（人間が操作）

| 確認内容 | 結果・記録 |
|---|---|
| Sepolia ENSv2 で `choice.eth` を登録し、最初の Agent を公開 | `docs/ens-manual-check.md` に実行記録。サーバー署名者への Sepolia ETH 送金は人間が実施 |
| ENS の役割分離（Owner / Reputation / Project 鍵の許可・拒否） | `scripts/ens_roles_check.py web-pm` で 11 項目（許可 3・拒否 8）が設計どおりであることを確認。Agent 詳細の権限表もオンチェーン値を表示 |
| ブラウザから Creator 自身の `.eth` の下に Agent を公開（連続 tx） | 人間が実施中に `nonce too low` を発見（P-23）。Claude が原因を特定し修正（コミット `cd99d56`）。修正後に人間が再実行して完了を確認 |
| PM Agent 登録後のコンソールエラー | 人間がスクリーンショットで報告し（P-25）、Claude が調査・対応 |
| Vercel / Render での公開動作 | 人間がログイン・環境変数投入・デプロイを実行し、公開 URL で動作確認 |
| World ID 実連携 | World 担当から受領した鍵を人間が Render に投入し、実機で認証完了を確認 |
| 公式サイトでテストネットの名前が確認できない問題 | Claude が提案した `scripts/ens_check.py` と `/ens/*` 画面（ENSIP-10 の一致確認）で人間が代替確認 |

### 5-2. 自動テスト（AI が作成、人間が実行して結果を確認）

| テスト | 内容 | 状態 |
|---|---|---|
| `contracts/test/Escrow.t.sol` | 承認者の検証、閾値到達で自動支払い、署名偽造・ハッシュ不一致・二重承認の拒否、再提出で承認無効化、紛争と裁定、承認なしでは支払い経路が無いこと、Human Task の支払先 | 10 件すべて成功（2026-09-26 に `forge test` で再確認） |
| `apps/api/scripts/smoke_flow.py` | ログイン → Agent 公開 → 案件 → 計画 → 入金 → AI 実行 → Human Task 指名・辞退・受諾 → 承認 1 人目で保留、2 人目で支払い → レビュー（二重投稿拒否）→ 紛争 → Jury 3 票で resolve | モックモードで通過を確認 |
| `apps/api/scripts/smoke_chain.py` | Sepolia 実機で openCase → fundTask → submit → approve → Paid | Sepolia で実行（提出前に再実行して tx を控えることを推奨） |
| `apps/api/scripts/smoke_creator.py` | 一時鍵の Creator が自分の `.eth` を登録し、API が返す calldata に署名して Agent を公開（プラットフォームの鍵は不使用） | Sepolia で通過を確認 |

### 5-3. AI 実装に対する人間の検証方法

- **コミット単位のレビュー**: AI が生成した差分はコミット前に人間が内容を確認し、コミットの指示（「コミットしてから次に進んで」）を人間が出している。
- **仕様書の検証基準（V1〜V19）に沿った操作確認**: 各機能を README の手順でローカル起動し、人間が画面操作で確認。Sepolia を使う項目は実機で確認。
- **ENS の実データ確認**: 画面表示とは別に、レジストリ・リゾルバを直接読むスクリプトとオンチェーンの `hasRootRoles` で人間が値を突き合わせた。
- **AI の提案を採用しなかった例**: リソース単位の EAC `grantRoles` はデプロイ済み ENSv2 で拒否されたため、AI の当初案を捨てて subname 単位の分離に変更（仕様書 追補 3「制約」）。Creator 所有 Agent での役割分離は未実装として明記。
- **未検証・既知の制限の明示**: 仕様書「やらないこと」「設計書との残差」、README「デモ・公開前チェックリスト」に、モックのまま残る箇所・本番運用に足りない箇所を人間が確認のうえ記載。

---

## 6. AI 生成物に人間が加えた主な修正・指摘

| 人間の指摘 | AI の対応 |
|---|---|
| アーキテクチャ設計書と実装の相違 | 差分表を作成し、Escrow・ワーカー・World 検証 5 行為を設計書に合わせて改修（追補 2） |
| DB 設計書の内部矛盾（承認者集合が無い、PM Agent をレビューできない 等 7 件） | 修正プロンプトを作成、実装側も追随 |
| UI の改行・配色 | モノトーン統一、等幅文字列・数値と単位の折り返し禁止 |
| ラベル一意性の不備 | ENS 名単位の一意制約に変更、処理中ジョブの起動時再実行を追加 |
| 連続 tx の `nonce too low` | nonce の直列化と、途中失敗（publishing）からの再開を実装 |
| ENS プライズ要件との乖離 | 3 鍵分離、Agent サブレジストリ、role 別 subname、`codrea.*` record キーへ統一、モック除去 |
| API 未再起動の見落とし | 人間が指摘し、AI が再起動して再確認 |

---

## 7. チームメンバー別の AI 利用

| 担当 | メンバー（GitHub） | AI 利用 |
|---|---|---|
| ENS・全体（仕様、コントラクト、API、Web、デプロイ、ドキュメント） | codreashinma / shinma_dev | 本文書 1〜6 章のとおり Claude Code を使用。コミットに `Co-Authored-By: Claude Fable 5.1` を付与 |
| World ID 検証（PR #1 `[API-07] Add World ID RP context endpoint`、PR #2 `[World ID] Verify proofs and prevent duplicate use`） | NameYume / Yume | **本人記入**: 使用ツール（　　　　　）／ AI を使った範囲（　　　　　）／ 人間が確認した内容（　　　　　）。コミットに AI のトレーラーは無い |
| 初期リポジトリ作成 | Kosuke-Mega | **本人記入**: （　　　　　） |

提出前に、World ID 担当と初期リポジトリ作成者が上記の空欄を埋めてください。

---

## 8. 参考: 関与の規模

| 項目 | 値 |
|---|---|
| 開発期間 | 2026-09-25 19:49 JST 〜 2026-09-26（ハッカソン期間内） |
| コミット数 | 57（うち Claude 共同作成トレーラー付き 41） |
| コード行数（`apps/`、`contracts/` の .py / .ts / .tsx / .sol。ライブラリ除く） | 約 8,300 行 |
| Claude Code セッション数 | 7（記録に残る人間の入力 98 件。主要なものを `docs/ai-prompts.md` に収録） |
