# -*- coding: utf-8 -*-
"""ValueScan custom exceptions."""

from __future__ import annotations

from typing import Any, Dict, Optional


class ValueScanError(Exception):
    """Base exception for all ValueScan-related errors."""

    def __init__(
        self,
        message: str = "ValueScan API error",
        *,
        code: Optional[int] = None,
        request_id: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.request_id = request_id
        self.detail = detail or {}

    def __repr__(self) -> str:
        parts = [self.message]
        if self.code is not None:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id!r}")
        return f"ValueScanError({', '.join(parts)})"

    def __str__(self) -> str:
        return self.__repr__()


class ValueScanAuthError(ValueScanError):
    """Authentication failure — invalid API key or signature."""


class ValueScanTimeoutError(ValueScanError):
    """Request timed out."""


class ValueScanConnectionError(ValueScanError):
    """Cannot connect to ValueScan endpoint."""


class ValueScanAPIError(ValueScanError):
    """API returned a non-200 code or business-level error."""
