"""
TenantAwareToggles — cascading module toggles with tenant-level overrides.

Priority (highest wins):
  1. Environment variable  RUNTIME__MODULES__<MODULE>__ENABLED
  2. Tenant DB override    (tenant_runtime_config table)
  3. Global config         (conf/default.yaml)
  4. Hard-coded default    True
"""

from __future__ import annotations

import logging

from vendor_runtime_sdk.runtime.config.toggles import KNOWN_MODULES, ModuleToggles, _DEFAULT_ENABLED

logger = logging.getLogger(__name__)


class TenantAwareToggles(ModuleToggles):
    """ModuleToggles with per-tenant database overrides."""

    def __init__(self, base_states: dict[str, bool], tenant_overrides: dict[str, bool]):
        merged = dict(base_states)
        for module, enabled in tenant_overrides.items():
            if module in KNOWN_MODULES:
                merged[module] = enabled
        super().__init__(_states=merged)
        self._tenant_overrides = tenant_overrides

    @classmethod
    async def for_tenant(cls, tenant_id: str, base: ModuleToggles | None = None) -> "TenantAwareToggles":
        """Build tenant-aware toggles by fetching overrides from DB."""
        base_states = base.get_all() if base else dict(_DEFAULT_ENABLED)
        tenant_overrides: dict[str, bool] = {}
        try:
            from dao.mysql.tenant_runtime_config import get_tenant_runtime_config_dao

            dao = get_tenant_runtime_config_dao()
            tenant_overrides = await dao.get_overrides(tenant_id)
        except Exception as exc:
            logger.warning(
                "TenantAwareToggles: failed to load overrides for tenant %s: %s",
                tenant_id,
                exc,
            )
        return cls(base_states=base_states, tenant_overrides=tenant_overrides)
