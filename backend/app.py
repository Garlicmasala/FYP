"""
NexusHub — Python (FastAPI) backend, built on Ethereum infrastructure
======================================================================
Three-chain backend for NexusHub. Each chain is a JSON ledger modelled like an
Ethereum node:
    - genesis block + chained "blocks" (each block header has a REAL SHA-256 hash,
      parentHash, stateRoot, transactionsRoot, receiptsRoot, gasUsed, timestamp)
    - "transactions" array, each with from (EOA address), to (contract), nonce,
      value, gasPrice (gwei), gasUsed, inputData, and an Ethereum-style receipt
    - "records" array: the semantic data, each pinned to a block + tx

Uploads compute a REAL SHA-256 of the file bytes (content addressed, like IPFS),
then the record is "mined" into a new block on the Content Chain.

Ledgers (AWS / Azure / GCP):
    backend/chains/identity_chain.json
    backend/chains/profile_chain.json
    backend/chains/content_chain.json

Run:  uvicorn app:app --host 0.0.0.0 --port 8000
Reset ledgers:  python reset_chains.py   (seeds the built-in Garrick admin)
"""

from __future__ import annotations

import hashlib
import json
import random
import re
import string
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from chain_hashes import (
    eth_address,
    identity_ref_from_email,
    root_of_hashes,
    sha256_hex,
    tx_from,
)

CONTRACT_ADDRESS = "0x4e59b44847b379578588920cA78FbF26c0B4956C"
GAS_LIMIT = 30000000
CHAIN_GAS = {"identity": 46221, "profile": 63412, "content": 87432}
VALIDATORS = {
    "identity": "0x7f1E5dE4b8E3F2a6C9D0A4b8E3F2a6C9D0A4b8E0",
    "profile": "0x6d2C9A4b8E3F2a6C9D0A4b8E3F2a6C9D0A4b8E1",
    "content": "0x9A0C4b8E3F2a6C9D0A4b8E3F2a6C9D0A4b8E2F",
}
BASE = Path(__file__).resolve().parent
CHAIN_DIR = BASE / "chains"
CHAIN_FILES = {
    "identity": CHAIN_DIR / "identity_chain.json",
    "profile": CHAIN_DIR / "profile_chain.json",
    "content": CHAIN_DIR / "content_chain.json",
}
META = {
    "identity": {"chain": "Identity Chain", "provider": "AWS", "contract": "Identity"},
    "profile": {"chain": "Profile Chain", "provider": "Azure", "contract": "Profile"},
    "content": {"chain": "Content Chain (GCP)", "provider": "GCP", "contract": "ContentVerification"},
}


# ---------------------------------------------------------------- utils
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _base_fee(block: int) -> int:
    return 20 + (block % 25)


def _load(key: str) -> dict:
    p = CHAIN_FILES[key]
    if not p.exists():
        raise HTTPException(500, f"Ledger {p.name} not found. Run `python reset_chains.py` first.")
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _save(key: str, data: dict) -> None:
    p = CHAIN_FILES[key]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def _ipfs_cid(sha: str) -> str:
    """Deterministic IPFS-style CID (Qm + 44 base58 chars)."""
    b = bytes.fromhex(sha)
    n = int.from_bytes(b, "big")
    out = []
    while n > 0:
        n, r = divmod(n, 58)
        out.append(BASE58[r])
    cid = "".join(reversed(out))
    return "Qm" + cid[:44].zfill(44)


# ---------------------------------------------------------------- app
app = FastAPI(title="NexusHub", version="1.0.0-fyp", description="Ethereum-infrastructure demo")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "app": "NexusHub", "infrastructure": "Ethereum (PoS, simulated)"}


@app.get("/api/chains")
def chains():
    out = {}
    for key in CHAIN_FILES:
        data = _load(key)
        out[key] = {
            **META[key],
            "chainId": data.get("chainId", 1),
            "consensus": data.get("consensus", "Proof of Stake"),
            "ledger_json": str(CHAIN_FILES[key]),
            "record_count": len(data.get("records", [])),
            "tx_count": len(data.get("transactions", [])),
            "block_count": len(data.get("blocks", [])),
            "head_block": data.get("head_block", 0),
            "head_block_hash": data.get("head_block_hash", ""),
        }
    return out


@app.get("/api/chain/{key}/records")
def chain_records(key: str):
    if key not in CHAIN_FILES:
        raise HTTPException(404, "Unknown chain. Use identity | profile | content.")
    data = _load(key)
    return {"chain": data["chain"], "provider": data["provider"], "consensus": data["consensus"],
            "chainId": data.get("chainId", 1), "contract_address": data.get("contract_address", ""),
            "head_block": data["head_block"], "head_block_hash": data["head_block_hash"],
            "record_count": len(data["records"]), "records": data["records"]}


@app.get("/api/blocks/{key}")
def chain_blocks(key: str):
    if key not in CHAIN_FILES:
        raise HTTPException(404, "Unknown chain. Use identity | profile | content.")
    data = _load(key)
    return {"chain": data["chain"], "head_block": data["head_block"],
            "blocks": list(reversed(data["blocks"]))}


@app.get("/api/tx/{key}/{txhash}")
def transaction(key: str, txhash: str):
    if key not in CHAIN_FILES:
        raise HTTPException(404, "Unknown chain. Use identity | profile | content.")
    data = _load(key)
    t = next((x for x in data["transactions"] if x["hash"] == txhash), None)
    if not t:
        raise HTTPException(404, "Transaction not found.")
    receipts = [x for x in data.get("receipts", []) if x["transactionHash"] == txhash]
    return {"chain": data["chain"], "transaction": t, "receipt": receipts[0] if receipts else t}


# ---------------------------------------------------------------- identity (AWS) — local accounts
class IdentityIn(BaseModel):
    email: str
    password: str
    displayName: str = ""
    role: str = "USER"


class LoginIn(BaseModel):
    email: str
    password: str


class VerifyEmailIn(BaseModel):
    email: str
    code: str


class SwitchIn(BaseModel):
    identityRef: str


class ProfileIn(BaseModel):
    identityRef: str
    username: str
    displayName: str = ""
    bio: str = ""
    websiteUrl: str = ""
    avatarColor: str = "#5865F2"
    bannerColor: str = "#12182A"


@app.post("/api/identity/register")
def register_identity(body: IdentityIn):
    """Create a LOCAL account on the Identity Chain (AWS) with EMAIL VERIFICATION."""
    email = body.email.strip().lower()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(400, "A valid email is required.")
    if len(body.password) < 4:
        raise HTTPException(400, "Password must be at least 4 characters.")
    if not body.displayName.strip():
        raise HTTPException(400, "A display name is required.")
    ref = identity_ref_from_email(email)
    data = _load("identity")
    if any(r["identityRef"] == ref for r in data["records"]):
        raise HTTPException(409, "An account with this email already exists on Identity Chain (AWS).")
    code = "".join(random.choices(string.digits, k=6))
    role = "USER"
    result = _mine(
        "identity",
        record={
            "identityRef": ref,
            "email": email,
            "password": body.password,          # plaintext for the demo only — hash in production
            "displayName": body.displayName.strip(),
            "role": role,
            "isActive": True,
            "emailVerified": False,
            "verificationCode": code,
            "registeredAt": _now_iso(),
            "balance": "0 ETH",
        },
        from_ref=ref,
        gas_used=CHAIN_GAS["identity"],
        contract_function="register(bytes32)",
        decoded_input=f"register(identityRef: {ref[:16]}…, email: {email})",
    )
    return {"ok": True, "chain": "Identity Chain (AWS)", "identityRef": ref,
            "address": result["from"], "role": role, "blockNumber": result["blockNumber"],
            "blockHash": result["blockHash"], "txHash": result["txHash"],
            "emailVerified": False, "verificationCode": code,
            "message": f"Email verification code sent to {email} (demo shows it here): {code}"}


@app.post("/api/identity/verify-email")
def verify_email(body: VerifyEmailIn):
    """Confirm the email with the 6-digit code 'sent' at registration."""
    email = body.email.strip().lower()
    ref = identity_ref_from_email(email)
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == ref), None)
    if not rec:
        raise HTTPException(404, "Account not found on Identity Chain (AWS).")
    if rec.get("emailVerified", False):
        return {"ok": True, "email": email, "alreadyVerified": True}
    if str(rec.get("verificationCode", "")) != str(body.code).strip():
        raise HTTPException(400, "Invalid verification code.")
    rec["emailVerified"] = True
    rec.pop("verificationCode", None)
    ev = _mine_event("identity", data, ref, 31209, "verifyEmail(bytes32)",
                     f"verifyEmail(email: {email})")
    return {"ok": True, "email": email, "verified": True,
            "user": {"identityRef": ref, "address": eth_address(ref), "email": email,
                     "displayName": rec.get("displayName", ""), "role": rec.get("role", "USER"),
                     "emailVerified": True},
            **ev}


@app.post("/api/identity/login")
def login(body: LoginIn):
    """Local login. Unverified emails cannot log in; returns the demo code."""
    ref = identity_ref_from_email(body.email.strip().lower())
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == ref), None)
    if not rec:
        raise HTTPException(401, "Account not found on Identity Chain (AWS).")
    if not rec.get("isActive", True):
        raise HTTPException(403, "Account disabled.")
    if not rec.get("emailVerified", False):
        code = rec.get("verificationCode") or "".join(random.choices(string.digits, k=6))
        raise HTTPException(403, f"Email not verified. Verification code (demo shows it here): {code}")
    if rec.get("password") != body.password:
        raise HTTPException(401, "Invalid email or password.")
    return {"ok": True, "user": {"identityRef": ref, "address": eth_address(ref),
                                  "email": rec["email"], "displayName": rec.get("displayName", ""),
                                  "role": rec.get("role", "USER"), "emailVerified": True}}


@app.post("/api/identity/switch")
def switch(body: SwitchIn):
    """Switch the active session to any local account (demo, no real auth)."""
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == body.identityRef), None)
    if not rec:
        raise HTTPException(404, "Account not found on Identity Chain (AWS).")
    if not rec.get("isActive", True):
        raise HTTPException(403, "Account disabled.")
    return {"ok": True, "user": {"identityRef": rec["identityRef"], "address": eth_address(rec["identityRef"]),
                                  "email": rec["email"], "displayName": rec.get("displayName", ""),
                                  "role": rec.get("role", "USER"), "emailVerified": rec.get("emailVerified", False)}}


@app.get("/api/identity/accounts")
def accounts():
    data = _load("identity")
    return {"chain": data["chain"], "provider": data["provider"], "record_count": len(data["records"]),
            "accounts": [{**{k: v for k, v in r.items() if k != "password" and k != "verificationCode"},
                          "address": eth_address(r["identityRef"])} for r in data["records"]]}


# ---------------------------------------------------------------- profile (Azure) — its own chain
def _latest_profile(data: dict, ref: str):
    """The current (non-superseded) profile record for an identityRef — the one
    with the highest blockNumber. Older records stay in the ledger forever."""
    recs = [r for r in data["records"] if r.get("identityRef") == ref]
    if not recs:
        return None
    return max(recs, key=lambda r: int(r.get("blockNumber", 0)))


def _identity_anchor(ref: str) -> dict:
    """Cross-chain anchor: the latest Identity Chain block/tx that owns this ref."""
    ident = _load("identity")
    rec = next((r for r in ident["records"] if r["identityRef"] == ref), None)
    if not rec:
        return {}
    return {"identityBlockNumber": rec.get("blockNumber"),
            "identityBlockHash": rec.get("blockHash"),
            "identityTxHash": rec.get("txHash")}


@app.post("/api/profile")
def create_profile(body: ProfileIn):
    """Register or UPDATE a public profile on the Profile Chain (Azure).
    Create = registerProfile(...); update = updateProfile(...) — in BOTH cases a NEW
    immutable record + block is appended. The previous record is NOT deleted or
    mutated; it is only marked superseded. Every profile record anchors to the
    owning Identity Chain block (one-to-one identity<->profile)."""
    ref = body.identityRef.strip()
    if not ref:
        raise HTTPException(400, "identityRef is required (log in first).")
    # identity must exist on Identity Chain (one-to-one)
    ident = _load("identity")
    if not any(r["identityRef"] == ref for r in ident["records"]):
        raise HTTPException(404, "No matching identity on Identity Chain (AWS). Register first.")
    username = body.username.strip().lower()
    if not username or not re.fullmatch(r"[a-z0-9_]{3,30}", username):
        raise HTTPException(400, "Username must be 3-30 chars: lowercase letters, digits or underscore.")
    data = _load("profile")
    existing = _latest_profile(data, ref)
    clash = next((r for r in data["records"] if r["username"] == username
                  and r.get("identityRef") != ref and not r.get("supersededByTx")), None)
    if clash:
        raise HTTPException(409, "Username already taken on Profile Chain (Azure).")
    avatar = body.avatarColor.strip() or "#1DA84E"
    banner = body.bannerColor.strip() or "#12182A"
    anchor = _identity_anchor(ref)
    rec = {
        "identityRef": ref,
        "username": username,
        "displayName": body.displayName.strip() or username,
        "bio": body.bio.strip(),
        "websiteUrl": body.websiteUrl.strip() or None,
        "avatarColor": avatar,
        "bannerColor": banner,
        "videoCount": existing.get("videoCount", 0) if existing else 0,
        "createdAt": existing.get("createdAt") or _now_iso(),
        **anchor,
    }
    if not existing:
        result = _mine("profile", record=rec, from_ref=ref, gas_used=CHAIN_GAS["profile"],
                       contract_function="registerProfile(string,string)",
                       decoded_input=f"registerProfile(username: {username}, avatar: {avatar})")
        action = "registerProfile"
    else:
        # Append a NEW immutable record; mark the old one superseded (never deleted).
        rec["videoCount"] = existing.get("videoCount", 0)
        result = _mine("profile", record=rec, from_ref=ref, gas_used=51209,
                       contract_function="updateProfile(string,string)",
                       decoded_input=f"updateProfile(username: {username}, avatar: {avatar})")
        # Re-read the ledger (the one _mine just wrote), then mark old record superseded.
        data = _load("profile")
        for r in data["records"]:
            if r.get("identityRef") == ref and r.get("blockNumber") == existing.get("blockNumber"):
                r["supersededByBlock"] = result["blockNumber"]
                r["supersededByTx"] = result["txHash"]
                r["isCurrent"] = False
            if r.get("blockNumber") == result["blockNumber"]:
                r["isCurrent"] = True
        _save("profile", data)
        action = "updateProfile"
    return {"ok": True, "chain": "Profile Chain (Azure)", "action": action,
            "username": username, "identityRef": ref, "address": eth_address(ref),
            "blockNumber": result["blockNumber"], "blockHash": result["blockHash"],
            "txHash": result["txHash"], "gasUsed": result["gasUsed"],
            "gasPriceGwei": result["gasPriceGwei"],
            "identityBlockNumber": anchor.get("identityBlockNumber"),
            "isUpdate": existing is not None}


@app.get("/api/profiles")
def profiles():
    """Current public profiles on the Profile Chain (Azure) — one per identityRef,
    resolving to the latest (non-superseded) record. Full history is visible at
    /api/chain/profile/records."""
    data = _load("profile")
    latest = {}
    for r in data["records"]:
        ref = r.get("identityRef")
        if ref not in latest or int(r.get("blockNumber", 0)) > int(latest[ref].get("blockNumber", 0)):
            latest[ref] = r
    return {"chain": data["chain"], "provider": data["provider"],
            "contract_address": data.get("contract_address", ""),
            "head_block": data["head_block"], "record_count": len(latest),
            "history_count": len(data["records"]),
            "profiles": list(reversed(list(latest.values())))}


@app.get("/api/profile/{username}")
def profile_by_username(username: str):
    """Public profile lookup (latest record), cross-referencing Identity Chain."""
    data = _load("profile")
    username = username.strip().lower()
    rec = None
    for r in data["records"]:
        if r.get("username") == username:
            if rec is None or int(r.get("blockNumber", 0)) > int(rec.get("blockNumber", 0)):
                rec = r
    if not rec:
        raise HTTPException(404, "No profile found on Profile Chain (Azure).")
    ident = _load("identity")
    i = next((x for x in ident["records"] if x["identityRef"] == rec["identityRef"]), None)
    history = [{"blockNumber": r.get("blockNumber"), "txHash": r.get("txHash"),
                "username": r.get("username"), "supersededByTx": r.get("supersededByTx")}
               for r in data["records"] if r.get("identityRef") == rec["identityRef"]]
    return {"chain": data["chain"], "provider": data["provider"],
            "contract_address": data.get("contract_address", ""),
            "head_block": data["head_block"], "username": rec["username"],
            "identityRef": rec["identityRef"], "address": eth_address(rec["identityRef"]),
            "displayName": rec["displayName"], "bio": rec.get("bio", ""),
            "websiteUrl": rec.get("websiteUrl"), "avatarColor": rec.get("avatarColor"),
            "bannerColor": rec.get("bannerColor"), "videoCount": rec.get("videoCount", 0),
            "registeredBlock": rec.get("blockNumber"), "registeredTx": rec.get("txHash"),
            "registeredAt": rec.get("createdAt"),
            "identityBlockNumber": rec.get("identityBlockNumber"),
            "identityBlockHash": rec.get("identityBlockHash"),
            "role": (i.get("role") if i else None), "emailVerified": (i.get("emailVerified") if i else None),
            "updateHistory": history}


# ---------------------------------------------------------------- content (GCP) — real SHA-256
@app.post("/api/content/register")
async def register_content(
    title: str = Form(...),
    uploader: str = Form(...),
    identity_ref: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a video: compute a REAL SHA-256 of the bytes, pin to a simulated
    IPFS node (CID), then mine the record into a new block on Content Chain."""
    title = title.strip()
    if not title:
        raise HTTPException(400, "A title is required.")
    if len(title) > 200:
        raise HTTPException(400, "Title must be 200 characters or fewer.")
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "File is empty.")
    sha = hashlib.sha256(raw).hexdigest()
    cid = _ipfs_cid(sha)
    data = _load("content")
    if any(r["sha256"] == sha for r in data["records"]):
        raise HTTPException(409, "This exact content is already registered on Content Chain (GCP).")
    ref = identity_ref if identity_ref else identity_ref_from_email(f"{uploader}@nexushub.demo")
    uploader_name = uploader.strip() or (ref[:8] if ref else "anonymous")
    record = {
        "title": title,
        "description": "",
        "uploaderUsername": uploader_name,
        "identityRef": ref,
        "sha256": sha,
        "ipfsCid": cid,
        "sizeBytes": len(raw),
        "mimeType": file.content_type or "video/mp4",
        "durationSeconds": 0,
        "thumbnailGradient": "linear-gradient(135deg,#1DA84E,#4ADE80)",
        "viewCount": 0,
        "isActive": True,
    }
    result = _mine("content", record=record, from_ref=ref, gas_used=CHAIN_GAS["content"],
                   contract_function="register(bytes32,string)",
                   decoded_input=f"register(hash: 0x{sha[:20]}…, cid: '{cid[:24]}…')")
    return {"ok": True, "chain": "Content Chain (GCP)", "sha256": sha, "ipfsCid": cid,
            "txHash": result["txHash"], "blockNumber": result["blockNumber"],
            "blockHash": result["blockHash"], "from": result["from"], "nonce": result["nonce"],
            "gasUsed": result["gasUsed"], "gasPriceGwei": result["gasPriceGwei"],
            "sizeBytes": len(raw), "contractAddress": data.get("contract_address", CONTRACT_ADDRESS)}


@app.get("/api/videos")
def list_videos(by: str = "", include_deleted: bool = False):
    """List ACTIVE Content Chain records. ?by=<identityRef | 0x address | username>."""
    data = _load("content")
    records = data["records"]
    if not include_deleted:
        records = [r for r in records if r.get("isActive", True)]
    if by:
        b = by.lower()
        records = [r for r in records
                   if (r.get("identityRef", "") or "").lower() == b
                   or (r.get("from", "") or "").lower() == b
                   or (r.get("uploaderUsername", "") or "").lower() == b]
    return {"chain": data["chain"], "count": len(records), "videos": list(reversed(records))}


@app.get("/api/verify/{sha256}")
def verify(sha256: str):
    data = _load("content")
    record = next((r for r in data["records"] if r["sha256"] == sha256.lower()), None)
    if not record:
        raise HTTPException(404, "No on-chain record found for this hash on Content Chain (GCP).")
    return {"verified": True, "title": record["title"],
            "uploaderUsername": record["uploaderUsername"], "registeredAt": record["timestamp"],
            "txHash": record["txHash"], "blockNumber": record["blockNumber"],
            "blockHash": record["blockHash"], "chain": "Content Chain (GCP)",
            "ipfsCid": record["ipfsCid"], "contractAddress": data.get("contract_address", CONTRACT_ADDRESS),
            "from": record.get("from", "")}


# ---------------------------------------------------------------- admin (modify the backend)
class RoleIn(BaseModel):
    identityRef: str
    role: str


class DisableIn(BaseModel):
    identityRef: str
    isActive: bool


class DeleteIn(BaseModel):
    sha256: str


def _require_admin(x_admin_ref: str):
    if not x_admin_ref:
        raise HTTPException(401, "Missing x-admin-ref header (your identityRef).")
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == x_admin_ref), None)
    if not rec or rec.get("role") != "ADMIN":
        raise HTTPException(403, "Admin privileges required.")


@app.get("/api/admin/users")
def admin_users(x_admin_ref: str = Header(None)):
    _require_admin(x_admin_ref)
    data = _load("identity")
    return {"count": len(data["records"]),
            "users": [{**{k: v for k, v in r.items() if k not in ("password", "verificationCode")},
                       "address": eth_address(r["identityRef"])} for r in data["records"]]}


@app.get("/api/admin/videos")
def admin_videos(x_admin_ref: str = Header(None)):
    _require_admin(x_admin_ref)
    data = _load("content")
    return {"count": len(data["records"]), "videos": list(reversed(data["records"]))}


@app.get("/api/admin/accounts-full")
def admin_accounts_full(x_admin_ref: str = Header(None)):
    """One-to-one view: each Identity Chain account joined with its current Profile
    Chain record and its Content Chain videos (active + deleted)."""
    _require_admin(x_admin_ref)
    ident = _load("identity")
    prof = _load("profile")
    cont = _load("content")
    out = []
    for r in ident["records"]:
        ref = r["identityRef"]
        pdata = [p for p in prof["records"] if p.get("identityRef") == ref]
        cur_profile = max(pdata, key=lambda p: int(p.get("blockNumber", 0))) if pdata else None
        vids = [v for v in cont["records"] if (v.get("identityRef") or "").lower() == ref.lower()]
        out.append({
            "identityRef": ref,
            "address": eth_address(ref),
            "email": r["email"], "displayName": r.get("displayName"),
            "role": r.get("role"), "isActive": r.get("isActive", True),
            "emailVerified": r.get("emailVerified", False),
            "identityBlock": r.get("blockNumber"),
            "identityTx": r.get("txHash"),
            "profile": ({
                "username": cur_profile.get("username"),
                "bio": cur_profile.get("bio"),
                "blockNumber": cur_profile.get("blockNumber"),
                "txHash": cur_profile.get("txHash"),
                "historyCount": len(pdata),
            } if cur_profile else None),
            "videos": [{"title": v["title"], "sha256": v["sha256"],
                        "blockNumber": v.get("blockNumber"), "isActive": v.get("isActive", True),
                        "viewCount": v.get("viewCount", 0)} for v in reversed(vids)],
            "videoCount": len(vids),
            "activeVideoCount": sum(1 for v in vids if v.get("isActive", True)),
        })
    return {"accounts": out,
            "totals": {"accounts": len(out),
                       "profiles": sum(1 for a in out if a["profile"]),
                       "videos": sum(a["videoCount"] for a in out)}}


@app.post("/api/admin/role")
def admin_role(body: RoleIn, x_admin_ref: str = Header(None)):
    _require_admin(x_admin_ref)
    if body.role not in ("USER", "CREATOR", "ADMIN"):
        raise HTTPException(400, "Role must be USER, CREATOR or ADMIN.")
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == body.identityRef), None)
    if not rec:
        raise HTTPException(404, "Account not found on Identity Chain (AWS).")
    old = rec.get("role")
    rec["role"] = body.role
    ev = _mine_event("identity", data, body.identityRef, 39412, "setRole(string)",
                     f"setRole({rec.get('displayName') or rec['email']}: {old} -> {body.role})")
    return {"ok": True, "email": rec["email"], "role": body.role, **ev}


@app.post("/api/admin/disable")
def admin_disable(body: DisableIn, x_admin_ref: str = Header(None)):
    _require_admin(x_admin_ref)
    data = _load("identity")
    rec = next((r for r in data["records"] if r["identityRef"] == body.identityRef), None)
    if not rec:
        raise HTTPException(404, "Account not found on Identity Chain (AWS).")
    if rec.get("isBuiltIn") and not body.isActive:
        raise HTTPException(400, "The built-in admin cannot be disabled.")
    rec["isActive"] = body.isActive
    ev = _mine_event("identity", data, body.identityRef, 29881, "setActive(bool)",
                     f"setActive({rec.get('displayName') or rec['email']}: {body.isActive})")
    return {"ok": True, "email": rec["email"], "isActive": body.isActive, **ev}


@app.post("/api/admin/video/delete")
def admin_video_delete(body: DeleteIn, x_admin_ref: str = Header(None)):
    """Mark a video deleted (isActive=false). The on-chain ownership record in its
    original block stays immutable; only the DB flag changes."""
    _require_admin(x_admin_ref)
    data = _load("content")
    rec = next((r for r in data["records"] if r["sha256"] == body.sha256.lower()), None)
    if not rec:
        raise HTTPException(404, "No on-chain record found for this hash on Content Chain (GCP).")
    if not rec.get("isActive", True):
        raise HTTPException(409, "Video is already deleted.")
    rec["isActive"] = False
    ev = _mine_event("content", data, body.sha256, 41003, "setActive(bool)",
                     f"setActive(video {body.sha256[:16]}…: deleted — on-chain record preserved)")
    return {"ok": True, "title": rec["title"], "deleted": True,
            "preservedBlock": rec.get("blockNumber"), "chainBlock": ev["blockNumber"],
            "blockHash": rec.get("blockHash")}


# ---------------------------------------------------------------- mining
def _mine(key: str, record: dict, from_ref: str, gas_used: int,
          contract_function: str, decoded_input: str) -> dict:
    """Append a data record AND mine an Ethereum-style block + tx + receipt."""
    data = _load(key)
    head = int(data["head_block"])
    block_number = head + 1
    parent_hash = data["head_block_hash"]
    from_addr = eth_address(from_ref)
    nonce = sum(1 for t in data["transactions"] if t.get("from", "").lower() == from_addr.lower())
    to_addr = data.get("contract_address", CONTRACT_ADDRESS)
    timestamp = _now_iso()
    tx_key = f"{key}:{block_number}:{nonce}:{record.get('email') or record.get('identityRef') or record.get('sha256')}"
    tx_hash = tx_from(tx_key)
    tx = {
        "hash": tx_hash, "from": from_addr, "to": to_addr, "nonce": nonce, "value": "0 ETH",
        "gasLimit": GAS_LIMIT, "gasPriceGwei": _base_fee(block_number),
        "maxFeePerGasGwei": _base_fee(block_number) + 4, "maxPriorityFeePerGasGwei": 1,
        "gasUsed": gas_used, "inputData": "0x" + sha256_hex(f"{contract_function}:{tx_key}")[2:],
        "decodedInput": decoded_input, "contractFunction": contract_function, "status": "success",
        "blockNumber": block_number, "blockHash": "", "timestamp": timestamp,
    }
    receipt = {"status": "success", "transactionHash": tx_hash, "blockNumber": block_number,
               "blockHash": "", "cumulativeGasUsed": gas_used,
               "logs": [{"address": to_addr, "topics": [sha256_hex(contract_function)], "data": tx_hash}]}
    block = {
        "number": block_number, "parentHash": parent_hash,
        "stateRoot": root_of_hashes([sha256_hex(json.dumps(r, ensure_ascii=False)) for r in data.get("records", []) + [record]]),
        "transactionsRoot": root_of_hashes([tx_hash]),
        "receiptsRoot": root_of_hashes([sha256_hex(json.dumps(receipt, ensure_ascii=False))]),
        "gasUsed": gas_used, "gasLimit": GAS_LIMIT, "baseFeePerGasGwei": _base_fee(block_number),
        "timestamp": timestamp, "miner": VALIDATORS[key], "transactions": [tx_hash],
    }
    header = {k: v for k, v in block.items() if k != "hash"}
    block_hash = sha256_hex(json.dumps(header, sort_keys=True, ensure_ascii=False))
    block["hash"] = block_hash
    tx["blockHash"] = block_hash
    receipt["blockHash"] = block_hash
    data["blocks"].append(block)
    data["transactions"].append(tx)
    data.setdefault("receipts", []).append(receipt)
    data["head_block"] = block_number
    data["head_block_hash"] = block_hash
    record.update({"blockNumber": block_number, "blockHash": block_hash, "txHash": tx_hash,
                   "from": from_addr, "nonce": nonce, "gasUsed": gas_used,
                   "gasPriceGwei": _base_fee(block_number), "status": "success",
                   "timestamp": timestamp})
    data["records"].append(record)
    _save(key, data)
    return {"from": from_addr, "nonce": nonce, "blockNumber": block_number, "blockHash": block_hash,
            "txHash": tx_hash, "gasUsed": gas_used, "gasPriceGwei": _base_fee(block_number)}


def _mine_event(key: str, data: dict, from_ref: str, gas_used: int,
                contract_function: str, decoded_input: str) -> dict:
    """Mine a tx + block onto an already-loaded ledger WITHOUT appending a data
    record (admin events: role change, disable, video removal)."""
    head = int(data["head_block"])
    block_number = head + 1
    parent_hash = data.get("head_block_hash") or data["blocks"][0]["hash"]
    from_addr = eth_address(from_ref)
    nonce = sum(1 for t in data["transactions"] if t.get("from", "").lower() == from_addr.lower())
    to_addr = data.get("contract_address", CONTRACT_ADDRESS)
    timestamp = _now_iso()
    tx_key = f"{key}:{block_number}:{nonce}:{contract_function}"
    tx_hash = tx_from(tx_key)
    tx = {"hash": tx_hash, "from": from_addr, "to": to_addr, "nonce": nonce, "value": "0 ETH",
          "gasLimit": GAS_LIMIT, "gasPriceGwei": _base_fee(block_number),
          "maxFeePerGasGwei": _base_fee(block_number) + 4, "maxPriorityFeePerGasGwei": 1,
          "gasUsed": gas_used, "inputData": "0x" + sha256_hex(f"{contract_function}:{tx_key}")[2:],
          "decodedInput": decoded_input, "contractFunction": contract_function, "status": "success",
          "blockNumber": block_number, "blockHash": "", "timestamp": timestamp}
    receipt = {"status": "success", "transactionHash": tx_hash, "blockNumber": block_number,
               "blockHash": "", "cumulativeGasUsed": gas_used,
               "logs": [{"address": to_addr, "topics": [sha256_hex(contract_function)], "data": tx_hash}]}
    block = {
        "number": block_number, "parentHash": parent_hash,
        "stateRoot": root_of_hashes([sha256_hex(json.dumps(r, ensure_ascii=False)) for r in data.get("records", [])]),
        "transactionsRoot": root_of_hashes([tx_hash]),
        "receiptsRoot": root_of_hashes([sha256_hex(json.dumps(receipt, ensure_ascii=False))]),
        "gasUsed": gas_used, "gasLimit": GAS_LIMIT, "baseFeePerGasGwei": _base_fee(block_number),
        "timestamp": timestamp, "miner": VALIDATORS[key], "transactions": [tx_hash],
    }
    header = {k: v for k, v in block.items() if k != "hash"}
    block_hash = sha256_hex(json.dumps(header, sort_keys=True, ensure_ascii=False))
    block["hash"] = block_hash
    tx["blockHash"] = block_hash
    receipt["blockHash"] = block_hash
    data["blocks"].append(block)
    data["transactions"].append(tx)
    data.setdefault("receipts", []).append(receipt)
    data["head_block"] = block_number
    data["head_block_hash"] = block_hash
    _save(key, data)
    return {"from": from_addr, "nonce": nonce, "gasUsed": gas_used,
            "gasPriceGwei": _base_fee(block_number), "blockNumber": block_number,
            "blockHash": block_hash, "txHash": tx_hash, "decodedInput": decoded_input}
