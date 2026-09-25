# ER図

> 参照資料: `docs/specs/20260925-agent-marketplace-mvp.md`（正本）、`docs/ETH_Globalユースケース.pdf`、`docs/01-アーキテクチャ図.svg`、`contracts/src/Escrow.sol`
> 最終更新: 2026-09-25

型の長さ・精度・CHECK 制約などの詳細は [database-design.md](./database-design.md) を参照。

```mermaid
erDiagram
    users ||--o{ agents : "creates"
    users ||--o{ cases : "orders as client"
    agents ||--o{ cases : "assigned as PM Agent"
    cases ||--|{ tasks : "has plan tasks"
    tasks ||--o| human_tasks : "published as"
    cases ||--o{ human_tasks : "belongs to"
    users ||--o{ human_tasks : "works as worker"
    cases ||--o{ reviews : "reviewed after completion"
    users ||--o{ reviews : "writes"
    cases ||--o| disputes : "disputed"
    disputes ||--o{ jury_votes : "collects"
    users ||--o{ jury_votes : "votes as juror"
    users ||--o{ world_verifications : "verified by World ID"

    users {
        uuid id PK
        varchar wallet_address UK "小文字正規化"
        varchar display_name "ENS 逆引き名のキャッシュ"
        boolean human_verified "world_verifications 有無の非正規化"
        timestamptz last_login_at
        timestamptz created_at
        timestamptz updated_at
    }

    agents {
        uuid id PK
        uuid creator_id FK
        varchar name
        varchar label UK "subname 用 slug"
        text description
        varchar category
        text rules "system prompt"
        integer fee_bps
        varchar payout_address "小文字正規化"
        varchar avatar_url
        varchar ens_name UK "label.choice.eth（キャッシュ）"
        varchar ens_tx_hash
        varchar status "draft|publishing|published|publish_failed"
        numeric rating_avg "ENS agent.rating と同期"
        integer rating_count "ENS agent.reviews と同期"
        integer completed_count "ENS agent.completed と同期"
        timestamptz published_at
        timestamptz created_at
        timestamptz updated_at
    }

    cases {
        uuid id PK
        uuid client_id FK
        uuid agent_id FK
        varchar title
        text description
        numeric budget "USDC 最小単位"
        date deadline
        varchar status "draft|planning|...|resolved"
        jsonb plan_json "PM Agent の計画（tasks, team）"
        varchar escrow_case_id UK "bytes32 hex"
        varchar deposit_tx_hash
        varchar release_tx_hash
        timestamptz created_at
        timestamptz updated_at
    }

    tasks {
        uuid id PK
        uuid case_id FK
        integer order_no
        varchar title
        text description
        varchar type "ai|human"
        varchar role "designer|frontend|backend|qa|field"
        numeric estimated_cost "USDC 最小単位"
        varchar status "todo|in_progress|done"
        varchar assignee_name "AI 専門 Agent 名"
        text deliverable "Markdown / URL"
        timestamptz completed_at
        timestamptz created_at
        timestamptz updated_at
    }

    human_tasks {
        uuid id PK
        uuid task_id FK,UK
        uuid case_id FK
        varchar title
        text description
        numeric reward "USDC 最小単位"
        varchar status "open|accepted|submitted|done"
        uuid worker_id FK
        text submission "テキスト / URL"
        text ai_check "PM Agent の照合コメント"
        timestamptz accepted_at
        timestamptz submitted_at
        timestamptz created_at
        timestamptz updated_at
    }

    reviews {
        uuid id PK
        uuid case_id FK
        uuid reviewer_id FK
        varchar target_type "agent|user"
        uuid target_id "agents.id or users.id"
        smallint rating "1..5"
        text comment
        varchar nullifier "World ID nullifier_hash"
        timestamptz created_at
        timestamptz updated_at
    }

    disputes {
        uuid id PK
        uuid case_id FK,UK
        text reason "差し戻し理由"
        jsonb summary_json "AI 論点サマリー"
        varchar status "open|closed"
        varchar outcome "release|refund"
        varchar resolve_tx_hash
        timestamptz closed_at
        timestamptz created_at
        timestamptz updated_at
    }

    jury_votes {
        uuid id PK
        uuid dispute_id FK
        uuid voter_id FK
        varchar vote "release|refund"
        varchar nullifier "World ID nullifier_hash"
        timestamptz created_at
        timestamptz updated_at
    }

    world_verifications {
        uuid id PK
        uuid user_id FK
        varchar action "review|jury|human-task"
        varchar signal "caseId / disputeId / taskId"
        varchar nullifier "World ID nullifier_hash"
        timestamptz verified_at
        timestamptz created_at
        timestamptz updated_at
    }
```

## リレーション概要

- users 1 : N agents — PM Agent Creator（`creator_id`）が複数の PM Agent を作成する。
- users 1 : N cases — 発注者（`client_id`）が複数の案件を作成する。
- agents 1 : N cases — 1 案件は 1 つの PM Agent を利用する。
- cases 1 : N tasks — PM Agent の計画で生成されたタスク（AI / Human）。`order_no` で実行順を持つ。
- tasks 1 : 0..1 human_tasks — `type=human` のタスクだけが Human Task Marketplace に公開される（`task_id` UNIQUE）。
- cases 1 : N human_tasks — 一覧画面で「元案件」を引くための冗長 FK（tasks 経由でも辿れる。理由は設計書 4.5 参照）。
- users 1 : N human_tasks — Human Task Worker（`worker_id`）。受注前は NULL。
- cases 1 : N reviews — `completed` / `resolved` 後に当事者が投稿。`target_type` + `target_id` で Agent か User かを指す（ポリモーフィック参照のため FK は張らない）。
- users 1 : N reviews — 投稿者（`reviewer_id`）。
- cases 1 : 0..1 disputes — 「差し戻し」で 1 件だけ作成（MVP では案件ごとに 1 紛争。`case_id` UNIQUE）。
- disputes 1 : N jury_votes — Jury の投票（3 票で確定）。`(dispute_id, voter_id)` UNIQUE。
- users 1 : N jury_votes — 投票者（`voter_id`）。当事者は投票不可（アプリ側で検証）。
- users 1 : N world_verifications — World ID 検証の記録。`(action, signal, nullifier)` UNIQUE で同一人物の二重投稿・二重投票・多重受注を防ぐ。
