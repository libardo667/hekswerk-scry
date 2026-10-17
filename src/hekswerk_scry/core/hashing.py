"""Deterministic SHA-256 content fingerprints for steps, maps, cards, and receipts."""

import hashlib
import json
from typing import Any


def canonical_json(payload: Any) -> str:
    """Serialize a JSON-compatible structure into one fixed string."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def fingerprint_data(payload: Any) -> str:
    """Return a short, readable SHA-256 fingerprint of a JSON-compatible structure.

    A fingerprint changes whenever the content changes. It is not a signature: anyone
    can compute one, so it shows *what* was checked, not *who* checked it.
    """
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest[:16]}"
