from __future__ import annotations

import pytest

from jobscan.domain.models import DisplayedCount, SliceSpec
from jobscan.domain.slicing import F_E_VALUES, F_JT_VALUES, is_terminal, needs_split, plan_children

ROOT = SliceSpec("data_engineer", "United States", "data engineer", "United States", "r2592000")


@pytest.mark.parametrize(
    ("count", "expected"),
    [
        (DisplayedCount("797", 797, False), False),
        (DisplayedCount("999", 999, False), False),
        (DisplayedCount("1,000", 1000, False), True),
        (DisplayedCount("2,000+", 2000, True), True),
        (DisplayedCount("", None, False), True),
        (None, True),
    ],
)
def test_needs_split(count: DisplayedCount | None, expected: bool) -> None:
    assert needs_split(count) is expected


def test_split_order_experience_then_job_type_then_sort() -> None:
    level1 = plan_children(ROOT)
    assert [c.f_e for c in level1] == list(F_E_VALUES)
    assert all(c.depth == 1 and c.f_jt is None for c in level1)
    level2 = plan_children(level1[3])
    assert [c.f_jt for c in level2] == list(F_JT_VALUES)
    assert all(c.f_e == "4" and c.depth == 2 for c in level2)
    level3 = plan_children(level2[0])
    assert [c.sort_by for c in level3] == ["DD", "R"]
    assert plan_children(level3[0]) == []
    assert is_terminal(level3[0])


def test_no_dual_sort_when_disabled() -> None:
    leaf = SliceSpec("r", "c", "k", "l", "r1", f_e="4", f_jt="F")
    assert plan_children(leaf, dual_sort=False) == []


def test_slice_ids_are_stable_and_distinct() -> None:
    child = plan_children(ROOT)[0]
    assert ROOT.slice_id("run1") == ROOT.slice_id("run1")
    assert ROOT.slice_id("run1") != ROOT.slice_id("run2")
    assert ROOT.slice_id("run1") != child.slice_id("run1")
