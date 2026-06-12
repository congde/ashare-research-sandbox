"""
Turn-scoped Fallback — model fallback management (§5.7)

FallbackManager restores the primary model at each turn start.
Fallback state is never persisted across turns.
"""

from vendor_runtime_sdk.runtime.fallback.manager import (
    AllFallbacksExhaustedError,
    FallbackAttribution,
    FallbackConfig,
    FallbackManager,
)

__all__ = [
    "FallbackManager",
    "FallbackConfig",
    "FallbackAttribution",
    "AllFallbacksExhaustedError",
]
