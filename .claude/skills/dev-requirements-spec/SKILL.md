---
name: dev-requirements-spec
description: dev-requirements-analysis が出力した docs/requirements/analysis.md（無ければ資料そのもの）をもとに、要件定義書・要件一覧（トレーサビリティ）を Markdown で、ユースケース図を SVG で /mnt/c/second-brain/ethglobal_hackathon/docs/requirements に作成・更新する。ユーザーが「要件定義書を作って」「要件定義をまとめて」「ユースケース図を作って」「トレーサビリティ表を作って」と言ったときに使う。資料から要求を洗い出す工程は先行スキル dev-requirements-analysis。
---

# dev-requirements-spec

分解・解析済みの要件を **要件定義書として清書する**スキル。
ここでは新しく要求を発掘しない（必要になったら `dev-requirements-analysis` に戻る）。

## 0. 作業ディレクトリ

**読み取り先・保存先はどちらも次のディレクトリ**（リポジトリ内の `docs/` ではない）:

```bash
DOCS_DIR=/mnt/c/second-brain/ethglobal_hackathon/docs
```

- 入力資料: `$DOCS_DIR/` 配下
- 出力先: `$DOCS_DIR/requirements/`（Markdown）／`$DOCS_DIR/requirements/img/`（**ユースケース図の SVG はすべてここに置く**）
- このディレクトリは **Obsidian の vault**（Windows 側 `C:\second-brain`）を WSL からマウントしたもの。以下に注意する:
  - `.obsidian/` 配下と `*:Zone.Identifier` は入力から除外する。
  - 改行は LF、文字コードは UTF-8 で書く。
  - Obsidian で開けるよう、**見出し・テーブル・チェックリストは標準の Markdown 記法**に収める。
- **解析対象から除外するファイル**（ユーザー指示 2026-09-25。読み込まない・出典にも使わない）:
  - `01-アーキテクチャ図.svg`
  - `02-アーキテクチャ図-WorldMiniApp案.svg`
  - `ETH_Globalユースケース.pdf`
  ユーザーが明示的に「この資料も見て」と指定した場合にだけ読む。その場合は使ったことを報告する。
- ディレクトリが存在しない／アクセスできない場合は、勝手に別の場所へ書かず、ユーザーにパスを確認する。
- ユーザーが `docs/idea.jpg` のような相対パスを渡した場合は、**`$DOCS_DIR` 起点として解決する**（`$DOCS_DIR/idea.jpg`）。

## 1. 入力を読む

| 入力 | 扱い |
|------|------|
| `$DOCS_DIR/requirements/analysis.md` | **一次入力**。ここにある ID・優先度・依存・矛盾・未決事項をそのまま引き継ぐ |
| `$DOCS_DIR/requirements/requirements.md` | 既存の要件定義書。差分更新のために必ず読む |
| `$DOCS_DIR/` 配下の元資料 | 出典の確認と、図に描く名称の裏取りに使う |

- `analysis.md` が無い場合は、**先に `dev-requirements-analysis` を実行するようユーザーに促す**。それでも進める場合は資料から直接起こし、「解析メモ無しで作成した」ことを前提・参照資料に明記する。
- `analysis.md` の ID は **絶対に振り直さない**。過不足があれば解析側に戻して直す。

## 2. 出力する

**要件定義書は必ず Markdown（`.md`）で作成する。** PDF・Word・Excel・HTML など他形式では出力しない（ユーザーから明示的に別形式を指定された場合のみ、Markdown を正本として作ったうえで変換する）。

出力先は **`$DOCS_DIR/requirements/`**（リポジトリ内の `docs/` には書かない）。**SVG は `img/` サブディレクトリに置く。** 無ければ作成する:

```bash
mkdir -p "$DOCS_DIR/requirements/img"
```

出力は次の 3 点:

| ファイル | 内容 |
|---|---|
| `requirements.md` | 要件定義書（Markdown） |
| `requirements-traceability.md` | 要件一覧・トレーサビリティ（Markdown） |
| `img/usecase-diagram.svg` | **ユースケース図（SVG）**。UC が多い場合は領域別に分割し、すべて `img/` 配下に置く |

既存ファイルがあれば内容を読み、上書きではなく **差分更新** とし、変更点を「変更履歴」に追記する。既存の要件 ID は再利用し、**振り直さない**（削除する場合は行を残して「廃止」と記す）。

Markdown の書き方ルール:

- 見出しは `#`（文書タイトル）→ `##`（章）→ `###`（節）の順に、レベルを飛ばさずに使う。
- 要件の一覧は **GFM のテーブル**（`| ... | ... |`）で書く。セル内改行が必要な場合は `<br>` を使い、行を割らない。
- セル内に `|` を含める場合は `\|` とエスケープする。
- **ユースケース図は SVG ファイル**として作り、その中身を Markdown に**インラインで埋め込む**（2-3 参照）。
- ユースケース図以外の図（状態遷移・シーケンス等）が必要なら Mermaid コードブロック（```` ```mermaid ````）で埋め込む。
- 画像は **`requirements/img/` 配下の自前ファイルのみ**参照する（`requirements.md` からは `img/<ファイル名>.svg` の相対パス）。外部 URL の画像は使わない。
- チェックリストは `- [ ]` / `- [x]`、強調は `**...**` を使う。装飾のための HTML は使わない。
- 文字コードは UTF-8、改行は LF。

### 2-1. `$DOCS_DIR/requirements/requirements.md`（要件定義書）

```markdown
# 要件定義書

> 参照資料: <読んだファイル一覧>
> 最終更新: YYYY-MM-DD

## 1. 概要
- システム名 / 目的 / 想定リリース

## 2. 前提・参照資料
| 資料 | 種別 | 読んだ範囲 | 備考（読めなかった場合はその旨） |

## 3. ビジネス要求（BR）
| ID | 要求 | 背景・価値 | 成功指標 | 出典 |

## 4. 利用者とユースケース（UC）
### 4-1. ユースケース図
<svg xmlns="http://www.w3.org/2000/svg" viewBox="..." width="..." height="..." style="max-width:100%;height:auto"> ... </svg>

[図を SVG で開く](img/usecase-diagram.svg)

> 詳細は「4-3. ユースケース」の記述を正とする。

### 4-2. アクター一覧
| アクター | 説明 | 権限 |

### 4-3. ユースケース
#### UC-001 <名称>
- アクター / 事前条件 / 基本フロー / 代替・例外フロー / 事後条件
- 関連要件: FR-00x, NFR-00x

## 5. 機能要件（FR）
| ID | 機能 | 内容（〜できること） | アクター | 優先度 | 依存 | 出典 |

主要な機能は表の下に補足（入出力項目・業務ルール・バリデーション）を書く。

## 6. 非機能要件（NFR）
| ID | 分類 | 要件（測定可能な形で） | 目標値 | 根拠/出典 |

分類は 性能 / 可用性 / セキュリティ / プライバシー / 運用・監視 / 拡張性 / UX / 法規制 を最低限カバーする。

## 7. 制約（CON）
| ID | 分類 | 制約内容 | 出典 |

## 8. データ要件
- 扱う主要データと、その正本の置き場所（DB / オンチェーン / 外部サービス）
- 個人情報・秘密情報の有無と取り扱い方針、保持期間

## 9. 外部インターフェース
| 相手先 | 方式 | 用途 | 認証 | 備考 |

## 10. スコープ外（OUT）
| ID | 内容 | 理由 |

## 11. リスクと未決事項
### リスク
| ID | リスク | 影響 | 対応方針 |

### 未決事項
| ID | 確認事項 | 影響する要件 | 確認先 | 状態 |

## 12. 変更履歴
| 日付 | 内容 |
```

### 2-2. `$DOCS_DIR/requirements/requirements-traceability.md`（要件一覧・トレーサビリティ）

全要件をフラットな 1 表にし、出典と後工程への紐づけを保つ。

```markdown
# 要件一覧（トレーサビリティ）

> 最終更新: YYYY-MM-DD

| ID | 種別 | 要件（1文） | 優先度 | 関連UC | 依存 | 出典（ファイル:ページ/行） | 状態 |
|---|---|---|---|---|---|---|---|
| FR-001 | 機能 | ... | Must | UC-001 | - | idea.jpg:③-1 | 確定 |
```

状態は `確定` / `仮` / `要確認` / `廃止` のいずれか。

出典欄はフルパスではなく **ファイル名** で書く（例: `idea.jpg:⑤-2`）。参照資料の一覧に `$DOCS_DIR` 起点であることを 1 行添える。

### 2-3. `$DOCS_DIR/requirements/img/usecase-diagram.svg`（ユースケース図）

**ユースケースは必ず UML のユースケース図として SVG で作成する。** Mermaid や PNG では出力しない（Mermaid にユースケース図の記法が無く、SVG ならテキスト検索・差分・拡大に耐えるため）。

**作成した SVG は `$DOCS_DIR/requirements/img/` に `.svg` ファイルとして保存したうえで、その中身を `requirements.md` に「インラインで埋め込む」。** 画像リンク（`![...](img/usecase-diagram.svg)`）による参照だけで済ませない — Markdown 単体で図が見える状態にする。

- 埋め込み位置は「4. 利用者とユースケース（UC）」の直下に `### 4-1. ユースケース図` として置く。
- 埋め込み方は **`<svg>` 要素をそのまま Markdown 本文に書く**（Markdown はインライン HTML を許すため、Obsidian の閲覧ビューで描画される）。
  - 前後を **空行で挟む**。コードフェンス（```` ``` ````）で囲まない — 囲むとコードとして表示される。
  - 根要素に `xmlns="http://www.w3.org/2000/svg"` を必ず残す。これが無いと描画されない。
  - 埋め込む側の根要素にだけ `style="max-width:100%;height:auto"` を足し、横幅がはみ出さないようにする。
  - XML 宣言（`<?xml ...?>`）や DOCTYPE は書かない。
- 図を分割した場合は、**すべての図**を同じ節に順に埋め込み、各図の直前に `#### <領域名>` と対象 UC 範囲を書く。
- 図の直後に「図と本文のどちらが正か」を 1 行添える（例: 詳細は 4-3 のユースケース記述を正とする）。
- **インラインの中身は `.svg` ファイルから機械的にコピーする。** Markdown 側の SVG を手で編集しない（2 か所が食い違うため）。図を直すときは `.svg` を直してからコピーし直す。
- GitHub は Markdown 内のインライン SVG をサニタイズして表示しない。GitHub でも見せたい場合は、インライン埋め込みに加えて `.svg` への相対リンク（`[図を開く](img/usecase-diagram.svg)`）を 1 行添える。

#### 描く要素

| 要素 | 記法 |
|---|---|
| アクター（人間） | 棒人間 + 直下にアクター名。システムの外側（境界矩形の左右）に置く |
| アクター（人間でない） | **棒人間にしない。** 角丸の矩形に `«system»`（外部システム）または `«AI agent»`（AI エージェント）のステレオタイプを付け、その下にアクター名を書く |
| ユースケース | 楕円 + 中に `UC-001` と名称。システム境界の内側に置く |
| システム境界 | 角丸の矩形。上部中央にシステム名 |
| 関連（association） | アクターとユースケースを結ぶ実線 |
| `<<include>>` | 破線 + 開いた矢印。**呼び出す側 → 呼ばれる側** |
| `<<extend>>` | 破線 + 開いた矢印。**拡張する側 → 拡張される側** |
| 汎化（generalization） | 実線 + 白抜き三角。子 → 親 |

#### レイアウト規則

- 左側に「人間のアクター」、右側に「人間でないアクター（外部システム・AI エージェント）」を置く。
- **人間でないものを棒人間で描かない。** 認証サービス・ブロックチェーンのレジストリ・スマートコントラクト・AI エージェントは、本システムの利用者ではなく連携相手なので、棒人間で描くと「ユーザー」に読み違えられる。角丸の箱＋ステレオタイプで描き、記法の凡例を図の下に置く。
  - 判断基準: **その相手は画面を操作したり意思決定をしたりする人間か？** いいえなら箱にする。
- ユースケースは業務の流れ順に上から並べ、関連するものを近くに置く。
- 線を交差させない。交差しそうなら、アクターの並び順かユースケースの位置を入れ替える。
- ユースケースが **15 個を超える場合はサブシステムごとに分割** し、`img/usecase-diagram-<領域名>.svg` として複数出力する。全体図も残す場合は `img/usecase-diagram.svg` を俯瞰図にする。UC が 15 個以下でも、アクターと関連線が交差して読めなくなる場合は分割してよい。
- 要件定義書の「4-2. アクター一覧」「4-3. ユースケース」と **アクター名・UC 番号・名称を完全に一致**させる。
- 「4-2. アクター一覧」は、**人間のアクター（利用者）／AI エージェント／外部システム に分けて**書く。外部システムの行には「何をするものか」を書き、**利用者ではないこと**を明記する。

#### SVG の書き方（必須ルール）

- ルートは `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 W H" width="W" height="H">`。`viewBox` を必ず付ける（拡大縮小のため）。
- **ダーク/ライト両対応**: 背景に `<rect fill="#ffffff">` を敷き、線と文字は濃色（`#1f2937` など）で描く。`currentColor` や CSS 変数に頼らない。
- フォントは `font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif"`、本文 `font-size="13"` 前後。日本語が化けないよう **テキストは `<text>` 要素**で書き、パス化しない。
- 文字は `text-anchor="middle"` + `dominant-baseline="middle"` で中央揃えにする。長い名称は `<tspan x="..." dy="14">` で折り返す（楕円の幅を超えさせない）。
- 矢印は `<defs>` に `<marker>` を定義して再利用する（`<<include>>` 用の開いた矢印、汎化用の白抜き三角）。
- 色は最小限（境界 `#94a3b8`、ユースケース塗り `#eff6ff` / 枠 `#3b82f6`、アクター `#1f2937`）。塗り分けで意味を持たせる場合は凡例を描く。
- `<style>` は使わず属性で指定する（Obsidian や GitHub での描画差を避けるため）。
- 手書きで組み立てる。作図ツールの巨大な出力を貼り付けない。

#### 骨組みの例

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 600" width="900" height="600">
  <defs>
    <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto">
      <path d="M0,0 L10,5 L0,10" fill="none" stroke="#64748b" stroke-width="1.5"/>
    </marker>
  </defs>
  <rect width="900" height="600" fill="#ffffff"/>
  <rect x="220" y="40" width="460" height="520" rx="12" fill="none" stroke="#94a3b8" stroke-width="1.5"/>
  <text x="450" y="66" text-anchor="middle" font-size="15" font-weight="bold" fill="#1f2937"
        font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif">&lt;システム名&gt;</text>

  <!-- アクター（棒人間） -->
  <g stroke="#1f2937" stroke-width="1.5" fill="none">
    <circle cx="110" cy="140" r="12"/><path d="M110,152 V186 M92,164 H128 M110,186 L96,212 M110,186 L124,212"/>
  </g>
  <text x="110" y="232" text-anchor="middle" font-size="13" fill="#1f2937"
        font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif">発注者</text>

  <!-- ユースケース -->
  <ellipse cx="380" cy="140" rx="112" ry="30" fill="#eff6ff" stroke="#3b82f6" stroke-width="1.5"/>
  <text x="380" y="134" text-anchor="middle" font-size="12" fill="#1f2937"
        font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif">UC-001</text>
  <text x="380" y="152" text-anchor="middle" font-size="13" fill="#1f2937"
        font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif">依頼を開始する</text>

  <!-- 関連 -->
  <line x1="134" y1="160" x2="268" y2="140" stroke="#64748b" stroke-width="1.5"/>

  <!-- include -->
  <line x1="380" y1="170" x2="380" y2="230" stroke="#64748b" stroke-width="1.5"
        stroke-dasharray="5 4" marker-end="url(#arrow)"/>
  <text x="392" y="200" font-size="11" fill="#64748b"
        font-family="'Noto Sans JP','Hiragino Sans','Yu Gothic',sans-serif">&lt;&lt;include&gt;&gt;</text>
</svg>
```

## 3. 検証と報告

出力前に自己点検する:

- [ ] `analysis.md` の全要件が要件定義書に反映されているか（欠落があれば理由を書く）
- [ ] すべての要件に **出典** が付いているか（出典が無い＝推測。要確認として明示したか）
- [ ] すべての UC が 1 つ以上の FR に紐づき、すべての FR が UC か BR に紐づいているか。孤立は理由を書く
- [ ] 非機能要件が測定可能な表現か（「速い」等が残っていないか）
- [ ] 依存関係に循環が無いか、参照先 ID が実在するか
- [ ] 要件 ID が重複していないか（`grep -oE '\b(BR|UC|FR|NFR|CON|OUT|Q)-[0-9]{3}\b' "$DOCS_DIR"/requirements/*.md | sort | uniq -c` で確認）
- [ ] `requirements.md` と `requirements-traceability.md` の ID 集合が一致しているか
- [ ] 出力が Markdown（`.md`）で、見出しレベル・テーブル記法が崩れていないか
- [ ] 保存先が `$DOCS_DIR/requirements/` になっているか（リポジトリ内の `docs/` に書いていないか）
- [ ] **SVG がすべて `$DOCS_DIR/requirements/img/` に保存されているか**（`requirements/` 直下に `.svg` を置いていないか。`ls "$DOCS_DIR"/requirements/*.svg` が空であること）
- [ ] `requirements.md` 内の SVG への相対リンクが `img/<ファイル名>.svg` になっているか
- [ ] **作成した SVG がすべて `requirements.md` にインラインで埋め込まれているか**（`grep -c '<svg ' requirements.md` と `ls img/usecase-*.svg | wc -l` が一致するか）
- [ ] 埋め込んだ SVG が `.svg` ファイルと同じ内容か（`style` 属性の追加以外に差分が無いか）
- [ ] **ユースケース図 SVG が well-formed か**（`xmllint --noout "$DOCS_DIR"/requirements/img/usecase-*.svg`。無ければ `python3 -c "import xml.etree.ElementTree as E;E.parse('<path>')"`）
- [ ] **SVG 内の UC 番号・名称・アクター名が `requirements.md` と一致しているか**
- [ ] **棒人間で描いたアクターがすべて人間か**（外部システム・スマートコントラクト・AI エージェントを棒人間にしていないか）
- [ ] SVG に `viewBox` と白背景の `<rect>` があり、線が交差していないか

最後にユーザーへ短く報告する:

- 作成・更新したファイル（**フルパスで示す**。要件定義書 / 要件一覧 / ユースケース図 SVG）
- 要件件数（種別ごと）と Must の件数
- 図の枚数と分割の方針
- **未決事項の一覧**（ユーザーの回答が必要なものを箇条書きで）

## 4. 後続への引き渡し

要件定義が固まったら、ユーザーに次を提案する（実行は求められたときだけ）:

- **`dev-architecture-design` スキル** — この要件定義を入力に、コンポーネント構成・インターフェース・技術選定を決め、アーキテクチャ図（SVG）と設計判断記録（ADR）を作る。**データの置き場所が決まるのはこの工程なので、必ず `dev-database-design` より先に実行する**
- `dev-database-design` スキル — アーキテクチャ設計の「データの配置」を入力に、オフチェーン（テーブル定義）とオンチェーン（コントラクトの状態・イベント・メタデータ構成）の両方を設計し、ER 図（SVG）を作る
- `github-tasks` スキル — Must の機能要件を開発タスクに分解して Project に登録する
