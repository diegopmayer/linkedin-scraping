from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass

from jobscan.config import RoleConfig


@dataclass(frozen=True)
class _CompiledRole:
    role_id: str
    include: tuple[re.Pattern[str], ...]
    exclude: tuple[re.Pattern[str], ...]
    boundary: tuple[re.Pattern[str], ...]


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in patterns)


class RoleMatcher:
    def __init__(self, roles: Mapping[str, RoleConfig]) -> None:
        self._roles = tuple(
            _CompiledRole(role_id, _compile(cfg.include), _compile(cfg.exclude), _compile(cfg.boundary))
            for role_id, cfg in roles.items()
        )

    def match(self, title: str) -> set[str]:
        return {
            role.role_id
            for role in self._roles
            if any(p.search(title) for p in role.include) and not any(p.search(title) for p in role.exclude)
        }

    def boundary_roles(self, title: str) -> set[str]:
        if self.match(title):
            return set()
        return {role.role_id for role in self._roles if any(p.search(title) for p in role.boundary)}
