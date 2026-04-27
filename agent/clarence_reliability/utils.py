from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{10,}\b"),
    re.compile(r"\b[A-Za-z0-9_]*TOKEN\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*SECRET\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}", re.IGNORECASE),
    re.compile(r"\b[A-Za-z0-9_]*PASSWORD\s*[:=]\s*['\"]?[^\s'\"]{8,}", re.IGNORECASE),
    re.compile(r"\bAPI[_-]?KEY\s*[:=]\s*['\"]?[A-Za-z0-9_./+=-]{8,}", re.IGNORECASE),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def looks_secret_shaped(value: str) -> bool:
    return any(pattern.search(value) for pattern in _SECRET_PATTERNS)


def iter_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            yield str(key)
            yield from iter_strings(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        for nested in value:
            yield from iter_strings(nested)
