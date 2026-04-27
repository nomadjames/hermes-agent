"""Offline reliability harness for Clarence-specific regression checks.

This package is intentionally pure/offline in v0. It must not import the live
agent loop, model tool discovery, MCP discovery, plugins, gateway senders, or
credential loaders.
"""

from .cases import BUILTIN_CASE_IDS, load_builtin_cases

__all__ = [
    "BUILTIN_CASE_IDS",
    "load_builtin_cases",
]
