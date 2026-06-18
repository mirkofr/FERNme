"""Verifiable data ownership (#4) — a tamper-evident, user-keyed audit log.

Every action is recorded as a link in an HMAC hash chain: each entry's hash binds
the previous hash + the action, keyed by the user's secret. Anyone holding the key
can replay the chain and detect if a single entry was altered, inserted, or
removed. (Production upgrade: per-user asymmetric keys so the USER signs and the
server can't forge — same chain, stronger ownership.)"""
from __future__ import annotations
import hmac, hashlib, json

GENESIS = "GENESIS"


def entry_hash(key: bytes, prev_hash: str, seq: int, ts: float,
               action: str, detail: dict) -> str:
    msg = f"{prev_hash}|{seq}|{ts}|{action}|{json.dumps(detail, sort_keys=True)}"
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def verify(entries, key: bytes):
    """Replay the chain. Returns (ok, broken_seq)."""
    prev = GENESIS
    for e in entries:
        h = entry_hash(key, prev, e["seq"], e["ts"], e["action"], e["detail"])
        if not hmac.compare_digest(h, e["hash"]):
            return False, e["seq"]
        prev = e["hash"]
    return True, None
