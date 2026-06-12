# -*- coding: utf-8 -*-
"""
Declarative Environment — §12.1 (Phase 4 P0)

Domain model for per-Session isolated execution environments.

An Environment declares:
  - base_image (container runtime)
  - packages (apt / pip / npm)
  - network policy (limited | unrestricted, allowed_hosts, MCP server access)
  - resource limits (memory, CPU, timeout)
  - env_vars (write-only; stored as Vault references or encrypted values;
    Session snapshots store only sha256 fingerprints — §5.5.1)

Design principles (§2.4):
  - Environment is an independent lifecycle resource (not tied to a single Agent)
  - Sessions reference Environments via environment_id at creation time
  - Updating an Environment affects only *new* Sessions; existing Sessions
    use the creation_snapshot (§5.5.1)
  - Archived Environments cannot be used for new Sessions
  - ETag concurrency control via updated_at (§14.9)
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


@dataclass(frozen=True)
class NetworkPolicy:
    """Network isolation policy for an Environment."""

    policy: Literal["unrestricted", "limited"] = "limited"
    allowed_hosts: tuple[str, ...] = ()
    allow_mcp_servers: bool = True
    allow_package_managers: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy,
            "allowed_hosts": list(self.allowed_hosts),
            "allow_mcp_servers": self.allow_mcp_servers,
            "allow_package_managers": self.allow_package_managers,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> NetworkPolicy:
        return cls(
            policy=d.get("policy", "limited"),
            allowed_hosts=tuple(d.get("allowed_hosts", ())),
            allow_mcp_servers=d.get("allow_mcp_servers", True),
            allow_package_managers=d.get("allow_package_managers", True),
        )


@dataclass(frozen=True)
class ResourceLimits:
    """Resource constraints for an Environment container."""

    memory_limit_mb: int = 2048
    cpu_limit: float = 2.0
    timeout_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.memory_limit_mb <= 0:
            raise ValueError("memory_limit_mb must be positive")
        if self.cpu_limit <= 0:
            raise ValueError("cpu_limit must be positive")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_limit_mb": self.memory_limit_mb,
            "cpu_limit": self.cpu_limit,
            "timeout_seconds": self.timeout_seconds,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ResourceLimits:
        return cls(
            memory_limit_mb=d.get("memory_limit_mb", 2048),
            cpu_limit=d.get("cpu_limit", 2.0),
            timeout_seconds=d.get("timeout_seconds", 3600),
        )


@dataclass(frozen=True)
class Packages:
    """Package declarations for an Environment."""

    apt: tuple[str, ...] = ()
    pip: tuple[str, ...] = ()
    npm: tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "apt": list(self.apt),
            "pip": list(self.pip),
            "npm": list(self.npm),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Packages:
        return cls(
            apt=tuple(d.get("apt", ())),
            pip=tuple(d.get("pip", ())),
            npm=tuple(d.get("npm", ())),
        )


@dataclass
class EnvironmentConfig:
    """
    Non-sensitive runtime constraints that are snapshotted into Session.

    This is the subset of Environment fields that appear in
    creation_snapshot.environment_config (§5.5.1).  env_vars are
    excluded — only their sha256 fingerprint is stored.
    """

    name: str
    base_image: str
    packages: Packages
    network: NetworkPolicy
    resources: ResourceLimits

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "base_image": self.base_image,
            "packages": self.packages.to_dict(),
            "network": self.network.to_dict(),
            "resources": self.resources.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> EnvironmentConfig:
        return cls(
            name=d["name"],
            base_image=d["base_image"],
            packages=Packages.from_dict(d.get("packages", {})),
            network=NetworkPolicy.from_dict(d.get("network", {})),
            resources=ResourceLimits.from_dict(d.get("resources", {})),
        )


@dataclass
class Environment:
    """
    Declarative execution environment — §12.1.

    Maps 1:1 to the MongoDB `environments` collection document.
    """

    environment_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    workspace_id: str = ""
    owner_id: str = ""
    name: str = ""
    base_image: str = "python:3.12-slim"
    packages: Packages = field(default_factory=Packages)
    network: NetworkPolicy = field(default_factory=NetworkPolicy)
    resources: ResourceLimits = field(default_factory=ResourceLimits)
    env_vars: Optional[Dict[str, str]] = None
    archived_at: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    # ── Validation ───────────────────────────────────────────────────────────

    def validate(self) -> None:
        """Raise ValueError if required fields are missing."""
        if not self.workspace_id:
            raise ValueError("workspace_id is required")
        if not self.owner_id:
            raise ValueError("owner_id is required")
        if not self.name:
            raise ValueError("name is required")
        if not self.base_image:
            raise ValueError("base_image is required")

    @property
    def is_archived(self) -> bool:
        return self.archived_at is not None

    @property
    def etag(self) -> str:
        """ETag for concurrency control — §14.9."""
        return str(self.updated_at)

    # ── Config extraction ────────────────────────────────────────────────────

    def to_config(self) -> EnvironmentConfig:
        """Extract non-sensitive EnvironmentConfig for Session snapshot (§5.5.1)."""
        return EnvironmentConfig(
            name=self.name,
            base_image=self.base_image,
            packages=self.packages,
            network=self.network,
            resources=self.resources,
        )

    def env_vars_sha256(self) -> str:
        """
        Compute sha256 fingerprint of env_vars for drift detection.

        Only the fingerprint is stored in Session creation_snapshot;
        never the raw values (§5.5.1).
        """
        if not self.env_vars:
            return ""
        canonical = json.dumps(self.env_vars, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(canonical.encode()).hexdigest()

    # ── Serialization ────────────────────────────────────────────────────────

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to MongoDB document format."""
        return {
            "_id": self.environment_id,
            "workspace_id": self.workspace_id,
            "owner_id": self.owner_id,
            "name": self.name,
            "base_image": self.base_image,
            "packages": self.packages.to_dict(),
            "network": self.network.to_dict(),
            "resources": self.resources.to_dict(),
            "env_vars": self.env_vars,
            "archived_at": self.archived_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> Environment:
        """Deserialize from MongoDB document."""
        return cls(
            environment_id=str(d.get("_id", d.get("environment_id", ""))),
            workspace_id=d.get("workspace_id", ""),
            owner_id=d.get("owner_id", ""),
            name=d.get("name", ""),
            base_image=d.get("base_image", "python:3.12-slim"),
            packages=Packages.from_dict(d.get("packages", {})),
            network=NetworkPolicy.from_dict(d.get("network", {})),
            resources=ResourceLimits.from_dict(d.get("resources", {})),
            env_vars=d.get("env_vars"),
            archived_at=d.get("archived_at"),
            created_at=d.get("created_at", time.time()),
            updated_at=d.get("updated_at", time.time()),
        )
