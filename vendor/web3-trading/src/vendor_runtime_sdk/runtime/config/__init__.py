"""
Config Cascade + Module Toggles (§3.4)

Config priority: YAML (default.yaml) → Env Vars → Apollo (highest)
Module toggles: runtime.modules.<module>.enabled
Emergency override: RUNTIME__MODULES__<MODULE>__ENABLED env var
"""

from vendor_runtime_sdk.runtime.config.cascade import (
    ConfigSource,
    dump_flat,
    log_effective_config,
    resolve,
    resolve_with_source,
)
from vendor_runtime_sdk.runtime.config.toggles import (
    KNOWN_MODULES,
    ModuleToggles,
)

__all__ = [
    # Toggles
    "ModuleToggles",
    "KNOWN_MODULES",
    # Cascade
    "ConfigSource",
    "resolve",
    "resolve_with_source",
    "dump_flat",
    "log_effective_config",
]
