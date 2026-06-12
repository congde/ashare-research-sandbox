# -*- coding: utf-8 -*-
"""KuCoin OpenAPI custom exceptions."""

from __future__ import annotations

from typing import Any, Dict, Optional


class KuCoinError(Exception):
    """Base exception for all KuCoin-related errors."""

    def __init__(
        self,
        message: str = "KuCoin API error",
        *,
        code: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.detail = detail or {}

    def __repr__(self) -> str:
        parts = [self.message]
        if self.code is not None:
            parts.append(f"code={self.code}")
        return f"KuCoinError({', '.join(parts)})"

    def __str__(self) -> str:
        return self.__repr__()


class KuCoinTimeoutError(KuCoinError):
    """Request timed out."""


class KuCoinConnectionError(KuCoinError):
    """Cannot connect to KuCoin endpoint."""


class KuCoinAPIError(KuCoinError):
    """API returned a non-success code or business-level error."""
