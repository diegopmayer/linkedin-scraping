from __future__ import annotations

from dataclasses import replace

from jobscan.domain.models import DisplayedCount, SliceSpec

DEFAULT_CAP = 1000
F_E_VALUES = ("1", "2", "3", "4", "5", "6")
F_JT_VALUES = ("F", "C", "P", "T")
SORTS = ("DD", "R")


def needs_split(count: DisplayedCount | None, *, cap: int = DEFAULT_CAP) -> bool:
    if count is None or count.value is None:
        return True
    return count.is_lower_bound or count.value >= cap


def plan_children(parent: SliceSpec, *, dual_sort: bool = True) -> list[SliceSpec]:
    depth = parent.depth + 1
    if parent.f_e is None:
        return [replace(parent, f_e=value, depth=depth) for value in F_E_VALUES]
    if parent.f_jt is None:
        return [replace(parent, f_jt=value, depth=depth) for value in F_JT_VALUES]
    if dual_sort and parent.sort_by is None:
        return [replace(parent, sort_by=value, depth=depth) for value in SORTS]
    return []


def is_terminal(spec: SliceSpec, *, dual_sort: bool = True) -> bool:
    return not plan_children(spec, dual_sort=dual_sort)
