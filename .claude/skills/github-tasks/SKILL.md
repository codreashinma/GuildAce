---
name: github-tasks
description: GitHub Projects「ethglobal_team_codrea」に開発タスクを作成する。ユーザーが「タスクを作って」「GitHub Projectsに登録して」「このTODOをチケット化して」「issueを切って」など、開発上のタスク・チケット・課題をProjectに追加したいときに使う。1件でも、仕様や議論から複数タスクへ分解する場合でも対象。
---

# github-tasks

GitHub Projects **`ethglobal_team_codrea`** に開発タスクを登録するスキル。`gh` CLI を使う。

## 1. 前提チェック

```bash
gh --version
gh auth status
```

- `gh` が無い場合: インストールを案内して止まる（例: `sudo apt install gh` / https://cli.github.com ）。
- Projects 操作には `project` スコープが必要。`gh auth status` の Token scopes に `project` が無ければ、ユーザーに次を実行してもらう:
  `! gh auth refresh -s project`
- 未ログインなら `! gh auth login` を案内する。

## 2. Project を特定する

Project のタイトルは `ethglobal_team_codrea`。オーナー（ユーザー or Organization）を探す:

```bash
# 自分のProject
gh project list --owner "@me" --format json --limit 100 \
  --jq '.projects[] | select(.title=="ethglobal_team_codrea") | {number, id, url, owner: .owner.login}'

# 所属Orgを順に探す
for org in $(gh org list --limit 100); do
  gh project list --owner "$org" --format json --limit 100 \
    --jq '.projects[] | select(.title=="ethglobal_team_codrea") | {number, id, url, owner: .owner.login}'
done
```

- 見つかった `owner` / `number` / `id`（`PVT_...`）を以降で使う。
- 見つからなければ、ユーザーにオーナー名（Org名）かProjectのURLを尋ねる。URL `https://github.com/orgs/<OWNER>/projects/<NUMBER>` または `https://github.com/users/<OWNER>/projects/<NUMBER>` から取り出せる。
- 判明したオーナーとProject番号は、このファイル末尾の「既知の設定」に追記しておくと次回から探索を省略できる。

## 3. フィールド情報を取得する

```bash
gh project field-list <NUMBER> --owner <OWNER> --format json
```

`Status`・`Priority`・`Size`・`Iteration` など、single-select フィールドの `id` と `options[].id` を控える。存在しないフィールドは設定しない（勝手に作らない）。

## 4. タスクを組み立てる

ユーザーの依頼（会話・仕様書・`docs/` 配下の資料など）から、タスクを次の形にまとめる:

- **タイトル**: 動詞で始まる短い一文（例: 「World ID 認証フローを実装する」）。日本語で可。
- **本文**（Markdown）:
  ```markdown
  ## 背景
  なぜ必要か

  ## やること
  - [ ] 具体的な作業1
  - [ ] 具体的な作業2

  ## 完了条件
  - 何ができたら Done か
  ```
- **フィールド**: `Status` は既定で `Backlog`。Priority/Size などは依頼から明確に読み取れる場合のみ設定。

大きな依頼は、1タスクが半日〜2日程度になるよう分解する。

**作成前に必ずユーザーへ一覧（タイトル・要約・設定するフィールド・作成形式）を提示して確認を取る。** 承認後に作成する。

## 5. 作成する

作成形式は2通り。ユーザーがリポジトリを指定した場合は Issue、そうでなければ Draft アイテム。

### A. Draft アイテム（既定）

```bash
gh project item-create <NUMBER> --owner <OWNER> \
  --title "<タイトル>" \
  --body "$(cat <<'EOF'
<本文>
EOF
)" \
  --format json
```

返ってくる JSON の `id`（`PVTI_...`）がアイテムID。

### B. リポジトリの Issue として作成し Project に追加

```bash
url=$(gh issue create --repo <OWNER>/<REPO> --title "<タイトル>" --body-file <本文ファイル>)
gh project item-add <NUMBER> --owner <OWNER> --url "$url" --format json
```

`--label` / `--assignee` はユーザーが指定したときのみ付ける。

### フィールド設定

```bash
gh project item-edit --id <ITEM_ID> --project-id <PROJECT_ID> \
  --field-id <FIELD_ID> --single-select-option-id <OPTION_ID>
```

テキスト/数値/日付フィールドは `--text` / `--number` / `--date YYYY-MM-DD` を使う。

本文は一時ファイル（スクラッチパッド）経由で渡すと、改行や記号のエスケープ事故を防げる。

## 6. 報告

作成したタスクを一覧で返す（タイトル・Issue URL またはアイテムID・設定したフィールド）。失敗したものがあればエラー内容と一緒に明記する。最後に Project の URL を添える。

## 既知の設定

- Project タイトル: `ethglobal_team_codrea`
- オーナー: `Kosuke-Mega`（ユーザー）
- Project 番号: `3`
- Project ID: `PVT_kwHOA682cc4BkoKp`
- URL: https://github.com/users/Kosuke-Mega/projects/3

### 主なフィールドID（2026-09-25 取得。変わっていたら field-list で再取得）

| フィールド | Field ID | 選択肢（Option ID） |
|---|---|---|
| Status | `PVTSSF_lAHOA682cc4BkoKpzhjYGfM` | Backlog `f75ad846` / Ready `61e4505c` / In progress `47fc9ee4` / In review `df73e18b` / Done `98236657` |
| Priority | `PVTSSF_lAHOA682cc4BkoKpzhjYGks` | P0 `79628723` / P1 `0a877460` / P2 `da944a9c` |
| Size | `PVTSSF_lAHOA682cc4BkoKpzhjYGkw` | XS `6c6483d2` / S `f784b110` / M `7515a9f1` / L `817d0097` / XL `db339eb2` |
| Estimate | `PVTF_lAHOA682cc4BkoKpzhjYGk0` | 数値 |
| Start date | `PVTF_lAHOA682cc4BkoKpzhjYGk4` | 日付 |
| Target date | `PVTF_lAHOA682cc4BkoKpzhjYGk8` | 日付 |
