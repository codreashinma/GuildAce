# ENS（ENSv2 / Sepolia）を実際に動かして手動確認する

## 前提

- ENSv2 は Sepolia ベータ。稼働中のコントラクトは `apps/api/app/config.py` の `ENSV2_*`（ensdomains/ens-cli と同じアドレス）。
- Universal Resolver（`0xeEeE…EeEe`）は現時点で v2 名を解決しないため、本アプリは **`.eth` レジストリ → サブレジストリ → リゾルバ** を直接たどって読む（`resolve_v2`）。
- サーバー署名者（`.env` の `SERVER_PRIVATE_KEY`）が `choice.eth` を所有し、Agent の subname を発行する。

| 役割 | 値 |
|---|---|
| サーバー署名者 | `0x9f8Ad401c288847d65dbB27e77713B9deb5C7171`（`apps/api/.env` に鍵あり。テスト専用） |
| 親名 | `choice.eth`（未登録・取得可能を確認済み） |
| .eth レジストリ | `0xBDC85dD5b15D7ecb354cd7cb6f2c50b4f2c4F0E2` |
| ETHRegistrar | `0xa88553F454b77203B0D036A05c894d555EAAa2Cc` |
| 登録料 | 約 8 USDC 相当（テスト用トークン。誰でも mint 可） |

## 0. 役割分離の設計（ENSv2 EAC / Permissioned Resolver）

運用鍵を 3 つに分け、それぞれが書ける場所をオンチェーンで限定している。

| 役割 | 鍵 | 名前 | リゾルバ | できること | できないこと |
|---|---|---|---|---|---|
| Owner | `SERVER_PRIVATE_KEY` | `<agent>.choice.eth` | 共有 OwnedResolver（Owner が root admin） | プロフィールの更新、subname の発行、Agent サブレジストリの作成 | reputation.* / project-* のレコード更新（別リゾルバで権限なし） |
| Reputation | `REPUTATION_PRIVATE_KEY` | `reputation.<agent>.choice.eth`（所有者 = Reputation 鍵） | Reputation リゾルバ（Reputation 鍵が root admin） | `codrea.agent.rating` / `reviews` / `completed` の更新 | Agent のプロフィール更新、subname の発行 |
| Project Agent | `PROJECT_PRIVATE_KEY` | `project-<n>.<agent>.choice.eth` | Project リゾルバ（Project 鍵が root admin） | Agent サブレジストリへの `register`（EAC `ROLE_REGISTRAR`、その Agent に閉じる）、`codrea.project.*` の更新 | Agent のリゾルバ変更、`choice.eth` 直下への発行、評価の更新 |

デプロイ済みの ENSv2 実装ではリソース単位の `grantRoles` が通らなかったため（root の admin でも `EACCannotGrantRoles`）、キー単位ではなく「役割ごとに subname とリゾルバを分ける」形で分離している。これはプライズ文の「Permissioned Resolvers enabling subname autonomy」に対応する。

検証は `scripts/ens_roles_check.py <label>` で行う。各鍵で `setText` / `register` / `setResolver` を eth_call し、許可・拒否が設計どおりかを表示する。画面（Agent 詳細の「権限管理」）も同じ値をオンチェーンから読んで出す。

## 1. 準備（1 回だけ）

1. サーバー署名者に Sepolia ETH を 0.05 ETH ほど送る（faucet 例: Google Cloud Web3 faucet、Alchemy faucet）。
2. セットアップを実行する（OwnedResolver デプロイ → `choice.eth` の commit/register → サブレジストリのデプロイと設定。所要 2〜3 分）。
   ```bash
   cd apps/api
   .venv/bin/python scripts/ens_setup.py --dry-run   # 送信せずに確認
   .venv/bin/python scripts/ens_setup.py             # 本番
   ```
3. 出力された 3 行を `apps/api/.env` に追記する。
4. 役割鍵を 2 つ作って Sepolia ETH を少額入れ、`REPUTATION_PRIVATE_KEY` / `PROJECT_PRIVATE_KEY` に設定する。役割ごとのリゾルバをデプロイし、出力を `.env` に追記して API を再起動する。
   ```bash
   .venv/bin/python scripts/ens_role_resolvers.py
   ```
   ```
   ENS_OWNED_RESOLVER=0x...
   ENS_PARENT_SUBREGISTRY=0x...
   ENS_WRITE_ENABLED=true
   ```

## 2. Agent を公開して確認する

1. 画面の「My Agents」→「＋ 新しい PM Agent」→ ラベルを決めて「ENS に公開する」。1〜2 分で `published` になり、ENS tx のリンクが出る。
2. 読み取りツールで確認する（鍵不要）。
   ```bash
   .venv/bin/python scripts/ens_check.py                       # choice.eth と DB 上の全 Agent / 人員
   .venv/bin/python scripts/ens_check.py web-pm.choice.eth     # 名前を指定
   ```
   `text[description]`、`text[codrea.agent.category]`、`text[codrea.agent.fee_bps]`、`addr` などが出れば成功。評価は `reputation.<label>.choice.eth` 側にある。
   ```bash
   .venv/bin/python scripts/ens_check.py reputation.web-pm.choice.eth
   .venv/bin/python scripts/ens_roles_check.py web-pm      # 役割分離の検証
   ```
3. Etherscan でも見られる。
   - tx: 画面の「ENS tx」リンク（`register` と `multicall` の 2 本）
   - リゾルバの Read Contract → `text(node, key)`。`node` は `ens_check.py` が出力する namehash。
4. cast でも読める（Foundry）。
   ```bash
   export PATH="$HOME/.foundry/bin:$PATH"
   RPC=https://ethereum-sepolia-rpc.publicnode.com
   # 親のサブレジストリ → subname のリゾルバ → text
   SUB=$(cast call 0xBDC85dD5b15D7ecb354cd7cb6f2c50b4f2c4F0E2 "getSubregistry(string)(address)" choice --rpc-url $RPC)
   RES=$(cast call $SUB "getResolver(string)(address)" web-pm --rpc-url $RPC)
   cast call $RES "text(bytes32,string)(string)" $(cast namehash web-pm.choice.eth) codrea.agent.category --rpc-url $RPC
   ```
5. 画面の Agent 詳細「ENS レコード」は、この読み取り結果をそのまま表示している。

## 3. レビューと完了で record が更新されることを確認する

- 案件を完了して支払うと `codrea.agent.completed` が、レビューを投稿すると `codrea.agent.rating` / `codrea.agent.reviews` が、Reputation 鍵の署名で `reputation.<agent>` に `setText` される。`ens_check.py` を再実行して値が変わることを確認する。

## 4. 会社の人員（会社が所有する .eth の下）

会社側は自分のウォレットで `.eth` を所有している必要がある。
1. 会社用のウォレットで Sepolia の名前を登録し、サブレジストリとリゾルバを用意する（`ens_setup.py` と同じ手順。`ENS_PARENT_NAME=<会社名>.eth` にして会社の鍵で実行するのが簡単）。
2. 画面「会社と人員」で会社を登録（所有者チェックが走る）→ 人員を追加 →「ENS に書き込む」。会社管理者のウォレットで 2 本の tx（`register`、`multicall`）に署名する。
3. `ens_check.py dan.<会社名>.eth` で `text[person.skills]` などを確認する。

## 5. ENSIP-10（ワイルドカード解決）の確認（2026-09-26）

- Sepolia の UniversalResolver（`0xeEeE…EeEe`）に `findResolver(dnsEncode("web-pm.choice.eth"))` を投げると resolver は `0x0`、`resolve()` は `ResolverNotFound` で revert する。v2 名は現時点で UniversalResolver からは見えない。
- 一方、v2 のリゾルバ実装（OwnedResolver / 役割リゾルバ）は `supportsInterface(0x9061b923)` = true で、`resolve(dnsEncode(name), text(node,key))` が直読みと同じ値を返す（`web-pm.choice.eth` の `codrea.agent.category` = `web`、`project-831.web-pm.choice.eth` の `codrea.project.title` も一致）。
- 本アプリはレジストリ直読みを正としつつ、`GET /ens/resolve` の `wildcard` で ENSIP-10 経路の一致を毎回確認して表示する（画面 `/ens`）。

## 6. Creator 所有の Agent（Creator の .eth の下に名前空間を作る）の実機確認（2026-09-26）

`scripts/smoke_creator.py` で、一時鍵（Creator）が自分の `.eth` を登録し、API が返す calldata に署名して Agent を名前空間として公開した。プラットフォームの鍵は一切使っていない（Reputation 鍵の初期 record 書き込みだけは worker）。

| 項目 | 値 / tx |
|---|---|
| Creator（一時鍵） | `0x326B82D8426C643a36eD7679C8900E55188b4c60` |
| `codrea-cr-2433ff.eth` 登録 | commit `0xf990fb3b…` → register `0x507b9ff3…`（テスト用トークン 8000021） |
| セルフサービス準備（`/ens/setup-calldata`、4 tx） | OwnedResolver `0xcD38EC6c…`（deploy `0x1a25ab7a…`、setResolver `0x9c39c06d…`）、UserRegistry `0x7047e725…`（deploy `0x9c72c482…`、setSubregistry `0x998736ee…`） |
| Agent 公開（`/agents/{id}/publish`、11 tx） | `web-pm-cr-1ea4.codrea-cr-2433ff.eth`（register `0x48c9d32c…`、profile `0x32b9f1a9…`） |
| Agent のサブレジストリ | `0x4BDAA8f196abE082fd61cb807…`（deploy `0x56913aa4…`、setSubregistry `0x95ef15a3…`） |
| Project 鍵に ROLE_REGISTRAR | `0x304d4d64…`（EAC `grantRootRoles`。Creator が root） |
| reputation subname | `reputation.web-pm-cr-1ea4.codrea-cr-2433ff.eth`（`0x1b49d15d…`、所有者 = Reputation 鍵、Reputation リゾルバ） |
| 専門 Agent | designer / frontend / backend / qa（`0xfdf54ee9…` ほか、record `0x364cfcc7…`） |
| 権限表（`GET /agents/{id}` の `ens_roles`） | Owner = Creator、Reputation、Project の 3 役割すべて verified=True |
| ENSIP-10 | `/ens/resolve` の `wildcard.matches = true` |
| 案件の project subname | `project-270.web-pm-cr-1ea4.codrea-cr-2433ff.eth`（openCase `0x46f6e78c…` 後に worker が Project 鍵で Creator のサブレジストリに発行。所有者 = Project 鍵、`codrea.project.title` 等を Project リゾルバに書き込み） |

platform（`choice.eth`）と creator（Creator の `.eth`）で、名前空間の構造とプラットフォーム鍵の権限範囲は同一。違いは「誰が root か」だけ。

### 6-2. 画面から `.eth` を登録する経路（`/ens/register-calldata`）の実機確認（2026-09-26）

一時鍵 `0xa2a6f524…` が API の calldata だけで `codrea-cr-cdc22c.eth` を登録し、続けて準備まで完了した。
mint `0xc7e64c3c…` → approve `0xd9141279…` → commit `0x93424abd…` → 75 秒 → register `0xc5453f88…` → OwnedResolver `0x1027E983…` / UserRegistry `0x81A0e8d1…`。
その後の Agent 公開（11 tx）と権限表 3 役割の verified も同じ実行で確認済み。

## トラブルシュート

- `execution reverted` で register が落ちる: commit から 60 秒未満、または `approve` 額不足。`ens_setup.py` を再実行すれば登録済み判定でスキップされる。
- `サブレジストリがありません`: 親名に `setSubregistry` が未実施。`ens_setup.py` を再実行。
- 画面の ENS レコードが空: API の `SEPOLIA_RPC_URL` が空か、`ENS_WRITE_ENABLED=false` でモック公開されている（tx hash が `0xmock…`）。

## 実行記録（2026-09-25）

| 項目 | 値 / tx |
|---|---|
| OwnedResolver | `0xDE7b6e8A92aEcF12239b5aad8ab89f827BFD8f8a`（tx `0xe5e91130…`） |
| `choice.eth` 登録 | commit `0x7953bcad…` → register `0xe62d27b1…` |
| サブレジストリ（UserRegistry） | `0xF174FBa4E328ce1C126243be52E02c84Aa75Ab27`（deploy `0x4c5683eb…`、setSubregistry `0x60e6d47f…`） |
| 最初の Agent | `web-pm-live.choice.eth`（tx `0x96624eab…`）。`agent.category=web` 等の text record と `addr` を API / `ens_check.py` / `cast` の 3 経路で読み取り確認 |

| 役割リゾルバ | Reputation `0xBBE26551f7f9F6d1DC344c275634F5f38F88af5d`（admin `0x7543…4845`）、Project `0x956D275DB002499d28Ee275fF5a3F1247a14F69c`（admin `0xBFE9…eD25`） |
| 役割分離の実機確認（2026-09-26） | `scripts/ens_roles_check.py web-pm` で 11 項目すべて設計どおり（許可 3・拒否 8）。Project 鍵が `project-831.web-pm.choice.eth` を発行し `codrea.project.*` を Project リゾルバに書き込み、Reputation 鍵が `reputation.web-pm.choice.eth` に評価 record を保持。Agent サブレジストリ `0x152b12b295785C7dCd5e4c7DD008983b658e803B` |
