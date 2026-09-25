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

## 1. 準備（1 回だけ）

1. サーバー署名者に Sepolia ETH を 0.05 ETH ほど送る（faucet 例: Google Cloud Web3 faucet、Alchemy faucet）。
2. セットアップを実行する（OwnedResolver デプロイ → `choice.eth` の commit/register → サブレジストリのデプロイと設定。所要 2〜3 分）。
   ```bash
   cd apps/api
   .venv/bin/python scripts/ens_setup.py --dry-run   # 送信せずに確認
   .venv/bin/python scripts/ens_setup.py             # 本番
   ```
3. 出力された 3 行を `apps/api/.env` に追記して API を再起動する。
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
   `text[description]`、`text[agent.category]`、`text[agent.fee_bps]`、`addr` などが出れば成功。
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
   cast call $RES "text(bytes32,string)(string)" $(cast namehash web-pm.choice.eth) description --rpc-url $RPC
   ```
5. 画面の Agent 詳細「ENS レコード」は、この読み取り結果をそのまま表示している。

## 3. レビューと完了で record が更新されることを確認する

- 案件を完了して支払うと `agent.completed` が、レビューを投稿すると `agent.rating` / `agent.reviews` が `setText` で更新される。`ens_check.py` を再実行して値が変わることを確認する。

## 4. 会社の人員（会社が所有する .eth の下）

会社側は自分のウォレットで `.eth` を所有している必要がある。
1. 会社用のウォレットで Sepolia の名前を登録し、サブレジストリとリゾルバを用意する（`ens_setup.py` と同じ手順。`ENS_PARENT_NAME=<会社名>.eth` にして会社の鍵で実行するのが簡単）。
2. 画面「会社と人員」で会社を登録（所有者チェックが走る）→ 人員を追加 →「ENS に書き込む」。会社管理者のウォレットで 2 本の tx（`register`、`multicall`）に署名する。
3. `ens_check.py dan.<会社名>.eth` で `text[person.skills]` などを確認する。

## トラブルシュート

- `execution reverted` で register が落ちる: commit から 60 秒未満、または `approve` 額不足。`ens_setup.py` を再実行すれば登録済み判定でスキップされる。
- `サブレジストリがありません`: 親名に `setSubregistry` が未実施。`ens_setup.py` を再実行。
- 画面の ENS レコードが空: API の `SEPOLIA_RPC_URL` が空か、`ENS_WRITE_ENABLED=false` でモック公開されている（tx hash が `0xmock…`）。
