"""
chain_hashes.py
===============
Deterministic hash helpers for NexusHub's Ethereum-style ledgers.

- identity_ref_from_email(email) -> 64-hex identity reference (deterministic)
- eth_address(ref)               -> 20-byte EOA address "0x" + 40 hex
- sha256_hex(s)                  -> real SHA-256 hex (block / tx hashes)
- root_of_hashes(hashes)         -> merkle-style root of a list of hex hashes
- tx_from(key)                   -> "0x" + 64-hex transaction hash (deterministic)
"""

from __future__ import annotations

import hashlib

MASK64 = (1 << 64) - 1
OFFSET = 14695981039346656037
PRIME = 1099511628211


def _fnv1a64(data: bytes) -> int:
    h = OFFSET
    for b in data:
        h ^= b
        h = (h * PRIME) & MASK64
    return h


def _fnv1a8lanes(s: str) -> int:
    """FNV-1a over 8 lanes (like a rough 'wide hash') for better dispersion."""
    b = s.encode("utf-8")
    lanes = [OFFSET] * 8
    for i, byte in enumerate(b):
        lane = i % 8
        lanes[lane] ^= byte
        lanes[lane] = (lanes[lane] * PRIME) & MASK64
    acc = 0
    for lane in lanes:
        acc = (acc ^ lane) & MASK64
    return acc


def _bytes16(x: int) -> bytes:
    return x.to_bytes(16, "big")


def identity_ref_from_email(email: str) -> str:
    """64-hex identity reference, deterministic from the email."""
    e = email.strip().lower()
    d = _fnv1a8lanes("nexushub-identity:" + e)
    return hashlib.sha256(_bytes16(d) + e.encode("utf-8")).hexdigest()


def eth_address(ref: str) -> str:
    """20-byte EOA address derived from a 64-hex identity reference."""
    r = ref if isinstance(ref, str) else str(ref)
    r = r.replace("0x", "")
    return "0x" + r[:40]


def sha256_hex(s) -> str:
    """Real SHA-256 hex digest of a string (block headers, tx data)."""
    if isinstance(s, str):
        s = s.encode("utf-8")
    return hashlib.sha256(s).hexdigest()


def root_of_hashes(hashes) -> str:
    """Merkle-style root over a list of 64-hex digests."""
    leaves = [h[2:] if h.startswith("0x") else h for h in hashes]
    if not leaves:
        return hashlib.sha256(b"empty-trie").hexdigest()
    while len(leaves) > 1:
        if len(leaves) % 2 == 1:
            leaves.append(leaves[-1])
        nxt = []
        for i in range(0, len(leaves), 2):
            nxt.append(hashlib.sha256((leaves[i] + leaves[i + 1]).encode()).hexdigest())
        leaves = nxt
    return leaves[0]


def tx_from(key: str) -> str:
    """Deterministic transaction hash for a ledger write key."""
    return "0x" + sha256_hex("nexushub-tx:" + key)
