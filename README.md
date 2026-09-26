# GuildAce — Digital Company Marketplace for the Agent Economy

*AI Agent × ENS × World × Ethereum. Built at ETHGlobal Tokyo by Team Codrea.*

GuildAce is a marketplace of **Digital Companies**: PM Agents that take a request in one sentence, break it into tasks, form a team of specialist AI agents and World‑verified humans, and run the whole job — contract, escrow, execution, delivery, approval and payment — as one company.

- **ENS** gives every Digital Company an identity and a trust record: the company, its specialist agents, its human workers, its ratings and every project it has run are ENS names with text records.
- **World** verifies that the important human actions — starting a request, approving a deliverable, reviewing, voting as a jury, accepting a human task — are performed by a real, unique human.
- **Ethereum** (an escrow contract on Sepolia) holds the funds per task and pays out only when the required number of human approvals has been signed.

The AI never moves money. It plans, delegates and reports; contracts and humans decide.

日本語版 README は [`docs/README.ja.md`](docs/README.ja.md) にあります。

## Live demo

| | URL | Notes |
|---|---|---|
| Web | https://choice-dun.vercel.app | Vercel. Sign in with a Sepolia wallet (SIWE) |
| API | https://choice-api-rcr5.onrender.com | Render, Singapore. `GET /health` and `GET /config` are public |

Connected services in production: Sepolia (escrow, ENS), World ID 4.0 (session proofs), Gemini (PM Agent planning). No mocks are enabled.

## How a job runs

1. **Choose a Digital Company** in the Marketplace. Cards show category, fee, rating and completed jobs; all of it comes from ENS records and human‑backed reviews.
2. **Write the request** in one sentence (e.g. "I want to build a website in 3 days. Budget is 12 USDC."). Pick the approvers and the number of approvals required, then confirm with World ID.
3. **The PM Agent plans.** It breaks the request into tasks, assigns AI tasks to the specialist agents that exist under its ENS name, and nominates a human from ENS‑registered workers for tasks that need a person.
4. **Open the escrow.** The client signs `openCase` (approvers and threshold are fixed on‑chain) and approves USDC. The chain worker then funds each task separately.
5. **Execute and deliver.** AI tasks run automatically; the nominated human accepts with World ID and submits their work. Each deliverable's hash and payee are recorded on‑chain with `submit`.
6. **Approve and pay.** Approvers verify with World ID and sign an EIP‑712 approval over (hash, payee). When the threshold is reached, the contract pays that task automatically. Disputes go to a World‑verified human jury.

## Repository layout

| Directory | Contents |
|---|---|
| `apps/web` | Next.js 16, wagmi + RainbowKit (SIWE sign‑in), `@worldcoin/idkit` v4 |
| `apps/api` | FastAPI, SQLAlchemy, Gemini (planning, human‑task nomination, dispute summaries), web3.py (ENSv2, Escrow), a chain worker thread |
| `contracts` | Foundry: `Escrow.sol` (per‑task `openCase / fundTask / submit / approve(EIP‑712) / dispute / resolve`) and `MockUSDC.sol` |
| `docker-compose.yml` | PostgreSQL 16 on port 5433 |
| `docs` | Spec, database design, ENS write‑up (`ens-submission.tex`), AI disclosure |

Every external integration (Sepolia, ENS writes, World ID, Gemini) **falls back to a mock when its keys are missing**, so the full flow runs locally without any credentials. The header shows `mock: …` for whatever is mocked.

## Run locally

```bash
# 1. Database
docker compose up -d db

# 2. API (http://localhost:8001)
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/uvicorn app.main:app --port 8001 --reload

# 3. Demo data (separate terminal)
.venv/bin/python scripts/seed.py

# 4. Web (http://localhost:3000)
cd ../web
pnpm install
cp .env.example .env.local
pnpm dev
```

Connect MetaMask to Sepolia, choose a user type in the header and sign in. With `DEV_LOGIN_ENABLED=true` a wallet‑less demo account is also available (it cannot sign on‑chain transactions).

Useful scripts (`apps/api/scripts`):

- `seed.py` — three Digital Companies (Web / Design / Wedding) and sample jobs
- `smoke_flow.py` — end‑to‑end backend test in mock mode (publish → plan → fund → execute → human task → pay → review → dispute → jury)
- `smoke_chain.py` — one real job on Sepolia (escrow + ENS)
- `smoke_creator.py` — publish a creator‑owned company under your own `.eth`
- `localize_agents_en.py` — rewrite seeded company profiles in English, on DB and on ENS
- `ens_check.py`, `ens_roles_check.py` — verify names, records and EAC roles on Sepolia

Contract tests: `cd contracts && forge test`.

## Connecting the real services

1. **Server signer** — a wallet with Sepolia ETH; `SERVER_PRIVATE_KEY`, `SEPOLIA_RPC_URL`. Optional `REPUTATION_PRIVATE_KEY` / `PROJECT_PRIVATE_KEY` for the ENS role split (see below).
2. **Escrow / MockUSDC** — `cd contracts && OPS_ADDRESS=<signer> forge script script/Deploy.s.sol --rpc-url $SEPOLIA_RPC_URL --broadcast --private-key $DEPLOYER_PRIVATE_KEY`, then set `ESCROW_ADDRESS` / `USDC_ADDRESS`.
3. **ENSv2 (Sepolia beta)** — register the platform parent name and run `scripts/ens_setup.py` once; set `ENS_OWNED_RESOLVER`, `ENS_PARENT_SUBREGISTRY`, `ENS_WRITE_ENABLED=true`.
4. **World ID** — create an app in the World Developer Portal with World ID 4.0; set `WORLD_APP_ID`, `WORLD_RP_ID`, `WORLD_RP_SIGNING_KEY`, `WORLD_VERIFY_ENABLED=true`. No portal action is needed (session‑proof model).
5. **Gemini** — `GEMINI_API_KEY` (model in `GEMINI_MODEL`).

## ENS: the company registry of the agent economy

Publishing a PM Agent mints a subname under the platform parent (`web-pm.choice.eth`) and turns it into a namespace:

```
web-pm.choice.eth                  the Digital Company (profile: description, category, fee, creator, endpoint)
├─ designer.web-pm.choice.eth      specialist AI agents the company employs (role, parent, kind = ai)
├─ frontend.  backend.  qa.
├─ reputation.web-pm.choice.eth    rating / reviews / completed — writable only by the Reputation key
└─ project-270.web-pm.choice.eth   one subname per job: title, escrow case id, client, status
```

- **Read from chain, not from our DB.** The Marketplace, the Agent page and team formation resolve these records from Sepolia (batched through Multicall3). `GET /ens/resolve` also runs an ENSIP‑10 wildcard check against the direct read.
- **Separation of powers with ENSv2 EAC roles.** The Owner key manages the name and profile; the Reputation key can only write rating records; the Project key holds `ROLE_REGISTRAR` on the company's own subregistry, so it can append project subnames but never edit the profile or ratings. The live role table is shown on the Agent page.
- **Bring your own name.** A creator can publish under their own `.eth` (`web-pm.shinmatest.eth`). The API only returns calldata; the creator's wallet deploys the resolver and subregistry (VerifiableFactory, CREATE2), mints the namespace and grants the scoped role. Receipts and records are verified on‑chain before the company is marked published.
- **Humans are on ENS too.** Worker companies register staff as subnames under their own `.eth` (`dan.field-co.eth`) with role, skills, location and availability. The PM Agent nominates only ENS‑backed candidates; approvers, jurors and reviewers are shown by ENS name via reverse lookup.
- **Audit view.** `GET /cases/{id}/audit` (no auth) lists a job's escrow transactions interleaved with the ENS names minted for it.

Full write‑up: [`docs/ens-submission.tex`](docs/ens-submission.tex).

## World: human authorization

Five actions require a World ID proof: starting a request, approving a task, posting a review, voting as a juror, accepting a human task. We use World ID 4.0 **session proofs**: the first verification binds a `session_id` to the account (one World ID = one account), later actions must present a proof from the same session. `(action, signal, session_id)` is stored UNIQUE to stop the same human acting twice on the same thing, and each proof's `session_nullifier` is stored UNIQUE to stop replays. Failed, expired or cancelled verifications never reach the payment path.

## Ethereum: contract and settlement

1. The client fixes approvers and threshold with `Escrow.openCase` and approves USDC.
2. The chain worker funds each task with `fundTask`; the PM fee is a task of its own.
3. Deliverables are recorded with `submit(hash, payee)`; the content stays off‑chain.
4. Approvers sign EIP‑712 approvals; the worker relays `approve`, and the contract pays the task as soon as the threshold is met.
5. `dispute` freezes a task; a three‑person World‑verified jury's majority is applied with `resolve`.

Sepolia: Escrow `0x2CE6C9f243557D0D7eb2EfD89C4F3A800Ffe0Bde`, MockUSDC `0xbf08e67Ac51E0499687B64F6E63489Bb1c1C1B2A`.

## Design invariants

1. The AI only proposes and generates. There is no off‑chain path that instructs a transfer; payment is decided by the contract from the approval count.
2. Deadlines alone never move funds.
3. Every important human action carries a World ID session proof; duplicates and replays are rejected.
4. An ENS name is not a permission. Only the approvers fixed in `openCase` can approve.
5. All on‑chain and ENS writes go through the chain worker (idempotency keys, retries, projections).

## Deployment notes

- API: Render web service `choice-api` (Docker, root `apps/api`), auto‑deployed from `master` of this repository. Environment variables are set in the Render dashboard; `DEV_LOGIN_ENABLED=false` in production.
- Web: Vercel project (named `choice` for historical reasons), deployed with `cd apps/web && vercel --prod`; `NEXT_PUBLIC_API_URL` points at the API.
- Database: Render PostgreSQL 16 `choice-db`.
- Changing the public URLs requires rewriting the `url` / `codrea.agent.endpoint` / `codrea.project.url` records on existing names with `scripts/ens_rewrite_urls.py`.
