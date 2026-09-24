"""
Cryptographic Savings Ledger and SHA-256 Merkle Tree for verifiable audit trails.
"""

import hashlib
import json
from typing import List, Dict, Any


class CryptographicSavingsLedger:
    """
    Append-only cryptographic ledger maintaining verifiable hashes and Merkle roots
    for hourly energy savings and demand response events.
    """

    def __init__(self):
        self.entries: List[Dict[str, Any]] = []

    def append_entry(self, entry: Dict[str, Any]) -> str:
        """
        Appends an entry and returns its deterministic SHA-256 leaf digest.
        """
        self.entries.append(entry)
        canonical_bytes = json.dumps(entry, sort_keys=True, separators=(',', ':')).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    def compute_merkle_root(self) -> str:
        """
        Computes the SHA-256 Merkle root over all recorded entries.
        """
        if not self.entries:
            return hashlib.sha256(b"FLEKSA_EMPTY_LEDGER").hexdigest()

        # Compute initial leaves
        current_level = [
            hashlib.sha256(json.dumps(e, sort_keys=True, separators=(',', ':')).encode("utf-8")).digest()
            for e in self.entries
        ]

        while len(current_level) > 1:
            next_level = []
            for i in range(0, len(current_level), 2):
                left = current_level[i]
                right = current_level[i + 1] if (i + 1) < len(current_level) else left
                combined = hashlib.sha256(left + right).digest()
                next_level.append(combined)
            current_level = next_level

        return current_level[0].hex()
