"""Shared exceptions for the ``db`` package."""

from __future__ import annotations


class ClientCapabilityError(RuntimeError):
    """Raised when the active database client driver lacks a required operation."""
