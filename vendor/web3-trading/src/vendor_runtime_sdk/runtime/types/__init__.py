# -*- coding: utf-8 -*-
"""
runtime.types — Pure DTO / Pydantic schemas shared between the engine
and the web/business layers.

Modules under this package MUST NOT import from:

* ``dao.*``
* ``web.*``
* ``lark.*``
* ``scrapy_v3.*``

They define the request / response shapes that engine call sites need
to construct without dragging the HTTP layer onto the import surface.

See ``docs/Agent-Engine-SDK-剥离方案.md`` §5 PR-E*c.
"""

from vendor_runtime_sdk.runtime.types.chat import (
    ExtraBodyModel,
    ImportedDocument,
    StaffMemberItem,
)

__all__ = [
    "ExtraBodyModel",
    "ImportedDocument",
    "StaffMemberItem",
]
