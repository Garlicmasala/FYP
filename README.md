# NexusHub

A video platform demo where **content ownership is verified on-chain** across three
independent blockchains hosted on three different cloud providers, built on an
**Ethereum infrastructure** model. Everything runs locally (or on this cloud VM) with
real SHA-256 hashing, mined Ethereum-style blocks, and persisted JSON ledgers — no
external APIs, no real backend network calls.

## Three chains (each = a simulated Ethereum node)

| Chain | Cloud | JSON ledger | Purpose |
|-------|-------|-------------|---------|
| Identity Chain | **AWS** | `backend/chains/identity_chain.json` | Local accounts as EOAs: address, nonce, role, **email-verified** |
| Profile Chain | **Azure** | `backend/chains/profile_chain.json` | Public metadata (username, bio) referencing identity |
| Content Chain | **GCP** | `backend/chains/content_chain.json` | Ownership proof: real SHA-256 + IPFS CID, mined immutably |

Blocks are chained by `parentHash`, block hashes are real SHA-256, each header carries
`stateRoot / transactionsRoot / receiptsRoot / gasUsed`, every write pays gas (gwei) and
returns an Ethereum-style receipt.

## Built-in admin (embedded in the backend)

| | |
|---|---|
| Email | `garrick@nexushub.dev` |
| Password | `garrick123` |
| Role | ADMIN (built-in, verified, cannot be disabled) |

Garrick is the only seeded account. Every new registration is `USER` and requires
**email verification** (the 6-digit code is shown on screen — no real mail service).

## Run

```bash
./run.sh            # backend 0.0.0.0:8000 + frontend 0.0.0.0:8080
./run.sh -fresh     # also wipe + re-seed ledgers
```

Open http://127.0.0.1:8080/ (frontend) and http://127.0.0.1:8000/docs (API).

## Features
- **Register** → email verification code (shown on screen) → verify → login.
- **Login** is blocked until the email is verified; a disabled account cannot log in.
- **Account switch** (top bar dropdown) → page refreshes → shows that user's own videos.
- **Upload** → drag & drop → client-side **auto SHA-256** (Web Crypto) → mined into a block.
- **Admin** (Garrick) → modify the backend on top of all user functions: change roles,
  disable users, delete videos (the on-chain record stays immutable in its original block).
- **Chain Explorer** → view block headers (parentHash chain) and records per chain
  (Identity / Profile / Content).
- **Profile Chain (Azure) — its own Ethereum node**: register or update a public profile
  (username, display name, bio, avatar/banner color, website) referencing your Identity
  address; create = `registerProfile` block, update = `updateProfile` block, each with its
  own gas/tx/receipt. Public lookup: `GET /api/profiles` and `GET /api/profile/{username}`
  (cross-references the Identity Chain for role/verified).
- **Verify** → paste any SHA-256 to look up its on-chain ownership record (no login).

## Reset

```bash
python3 backend/reset_chains.py     # wipes all three ledgers, re-seeds Garrick admin
```

See `backend/README.md` for the full API reference.
