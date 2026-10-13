"""
reset_chains.py
===============
Reset all three chain ledgers to EMPTY Ethereum-style state, then embed ONE
built-in admin account: Garrick (garrick@nexushub.dev / garrick123) as ADMIN on
the Identity Chain (AWS). No other dummy data.

    Identity Chain (AWS)  -> chains/identity_chain.json
    Profile  Chain (Azure)-> chains/profile_chain.json
    Content  Chain (GCP)  -> chains/content_chain.json

Run:  python reset_chains.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from chain_hashes import eth_address, identity_ref_from_email, root_of_hashes, sha256_hex

CONTRACT_ADDRESS = "0x4e59b44847b379578588920cA78FbF26c0B4956C"
CHAIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chains")
GENESIS_TIME = "2025-01-01T00:00:00.000Z"
GENESIS_NUMBER = 1002400
VALIDATOR = "0x7f1E5dE4b8E3F2a6C9D0A4b8E3F2a6C9D0A4b8E0"

ADMIN_EMAIL = "garrick@nexushub.dev"
ADMIN_PASSWORD = "garrick123"
ADMIN_DISPLAY = "Garrick"
ADMIN_ROLE = "ADMIN"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def genesis_block(key: str) -> dict:
    parent_hash = sha256_hex(f"NexusHub genesis {key}")
    return {
        "number": GENESIS_NUMBER,
        "hash": sha256_hex(json.dumps({"number": GENESIS_NUMBER, "parentHash": parent_hash, "key": key})),
        "parentHash": parent_hash,
        "stateRoot": sha256_hex("empty-state:" + key),
        "transactionsRoot": sha256_hex("empty-trie"),
        "receiptsRoot": sha256_hex("empty-trie"),
        "gasUsed": 0, "gasLimit": 30000000, "baseFeePerGasGwei": 1,
        "timestamp": GENESIS_TIME, "miner": "0x0000000000000000000000000000000000000000",
        "transactions": [],
    }


CHAINS = [
    {"key": "identity_chain",
     "contract_address": "0x6c207cF3923E277E2d5d4a5b8A7C1f4D1B0E5A22",
     "contract": "Identity", "chain": "Identity Chain", "provider": "AWS",
     "role": "root trust layer — local accounts, addresses and identity references"},
    {"key": "profile_chain",
     "contract_address": "0x9A7E2d6Fb5C8143E0A1D2C3B4E5F60718293A4B5C",
     "contract": "Profile", "chain": "Profile Chain", "provider": "Azure",
     "role": "public metadata (username, bio) — references Identity Chain identityRef"},
    {"key": "content_chain",
     "contract_address": CONTRACT_ADDRESS,
     "contract": "ContentVerification", "chain": "Content Chain (GCP)", "provider": "GCP",
     "role": "ownership proof — SHA-256 digest + IPFS CID, immutable"},
]


def main() -> None:
    os.makedirs(CHAIN_DIR, exist_ok=True)
    for c in CHAINS:
        gen = genesis_block(c["key"])
        data = {
            "chain": c["chain"], "provider": c["provider"], "contract": c["contract"],
            "chainId": 1, "consensus": "Proof of Stake",
            "contract_address": c["contract_address"], "role": c["role"],
            "head_block": GENESIS_NUMBER, "head_block_hash": gen["hash"],
            "blocks": [gen], "transactions": [], "receipts": [], "records": [],
        }
        path = os.path.join(CHAIN_DIR, f"{c['key']}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"reset {path} -> genesis {gen['hash'][:18]}...")

    # embed the built-in admin: Garrick on the Identity Chain (AWS)
    ipath = os.path.join(CHAIN_DIR, "identity_chain.json")
    with open(ipath, "r", encoding="utf-8") as f:
        data = json.load(f)
    ref = identity_ref_from_email(ADMIN_EMAIL)
    head = GENESIS_NUMBER
    from_addr = eth_address(ref)
    tx_hash = sha256_hex(f"identity:{head+1}:0:register:garrick")
    tx_hash = "0x" + tx_hash
    rec = {
        "identityRef": ref, "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
        "displayName": ADMIN_DISPLAY, "role": ADMIN_ROLE, "isActive": True,
        "emailVerified": True, "registeredAt": _now_iso(), "balance": "0 ETH",
        "isBuiltIn": True, "blockNumber": head + 1, "txHash": tx_hash,
        "from": from_addr, "nonce": 0, "gasUsed": 46221, "gasPriceGwei": 21,
        "status": "success", "timestamp": _now_iso(),
    }
    receipt = {"status": "success", "transactionHash": tx_hash, "blockNumber": head + 1,
               "blockHash": "", "cumulativeGasUsed": 46221,
               "logs": [{"address": data["contract_address"],
                         "topics": [sha256_hex("register(bytes32)")], "data": tx_hash}]}
    block = {
        "number": head + 1, "parentHash": data["head_block_hash"],
        "stateRoot": root_of_hashes([sha256_hex(json.dumps(rec, ensure_ascii=False))]),
        "transactionsRoot": root_of_hashes([tx_hash]),
        "receiptsRoot": root_of_hashes([sha256_hex(json.dumps(receipt, ensure_ascii=False))]),
        "gasUsed": 46221, "gasLimit": 30000000, "baseFeePerGasGwei": 21,
        "timestamp": _now_iso(), "miner": VALIDATOR, "transactions": [tx_hash],
    }
    header = {k: v for k, v in block.items() if k != "hash"}
    block_hash = sha256_hex(json.dumps(header, sort_keys=True, ensure_ascii=False))
    block["hash"] = block_hash
    rec["blockHash"] = block_hash
    receipt["blockHash"] = block_hash
    data["blocks"].append(block)
    data["transactions"].append(tx := {"hash": tx_hash, "from": from_addr, "to": data["contract_address"],
                                       "nonce": 0, "value": "0 ETH", "gasLimit": 30000000,
                                       "gasPriceGwei": 21, "maxFeePerGasGwei": 25,
                                       "maxPriorityFeePerGasGwei": 1, "gasUsed": 46221,
                                       "inputData": "0x" + sha256_hex("register:garrick")[2:],
                                       "decodedInput": f"register(builtin admin: {ADMIN_EMAIL})",
                                       "contractFunction": "register(bytes32)", "status": "success",
                                       "blockNumber": head + 1, "blockHash": block_hash,
                                       "timestamp": _now_iso()})
    data["receipts"].append(receipt)
    data["records"].append(rec)
    data["head_block"] = head + 1
    data["head_block_hash"] = block_hash
    with open(ipath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"embedded ADMIN {ADMIN_EMAIL} -> {from_addr} (block #{data['head_block']})")


if __name__ == "__main__":
    main()
