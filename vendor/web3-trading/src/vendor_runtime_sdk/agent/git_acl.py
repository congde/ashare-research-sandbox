# -*- coding: utf-8 -*-
"""Minimal vendorized git ACL models for runtime compatibility."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AgentGitAclEntry:
    """Repo-level ACL entry used by ephemeral git token issuer."""

    repo: str
    access: str


__all__ = ["AgentGitAclEntry"]
