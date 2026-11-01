"""Group job ids that are copies of one posting (same job re-posted per city or per search).

Two jobs are the same posting when they have the same company, the same title (after
normalising) and descriptions that are identical or nearly so. Near-identical covers
re-posts that differ only in a city name or a salary line; the title check keeps
apart different openings that share a company template.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from jobscan.domain.text import normalise

SHINGLE_WORDS = 5
_WORD = re.compile(r"\w+")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class PostingCandidate:
    job_id: str
    company: str
    title: str
    description: str
    posted_at: date | None = None


def posting_scope(company: str, title: str) -> tuple[str, str]:
    return (_NON_ALNUM.sub(" ", normalise(company)).strip(), _NON_ALNUM.sub(" ", normalise(title)).strip())


def shingles(text: str, size: int = SHINGLE_WORDS) -> frozenset[str]:
    words = _WORD.findall(normalise(text))
    if len(words) <= size:
        return frozenset({" ".join(words)})
    return frozenset(" ".join(words[i:i + size]) for i in range(len(words) - size + 1))


def similarity(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self._parent = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra


def _representative(members: Sequence[PostingCandidate]) -> str:
    """Newest posting wins; ties go to the smallest job id so the choice is stable."""
    newest = max((m.posted_at for m in members if m.posted_at is not None), default=None)
    pool = [m for m in members if m.posted_at == newest] if newest is not None else list(members)
    return min(pool, key=lambda m: (len(m.job_id), m.job_id)).job_id


def group_postings(candidates: Iterable[PostingCandidate], *, min_similarity: float) -> dict[str, str]:
    """Map every job id to the job id that represents its posting."""
    by_scope: dict[tuple[str, str], list[PostingCandidate]] = defaultdict(list)
    for candidate in candidates:
        by_scope[posting_scope(candidate.company, candidate.title)].append(candidate)

    mapping: dict[str, str] = {}
    for members in by_scope.values():
        groups = _UnionFind(m.job_id for m in members)
        if len(members) > 1:
            texts = [shingles(m.description) for m in members]
            for i in range(len(members)):
                for j in range(i + 1, len(members)):
                    if similarity(texts[i], texts[j]) >= min_similarity:
                        groups.union(members[i].job_id, members[j].job_id)
        clusters: dict[str, list[PostingCandidate]] = defaultdict(list)
        for member in members:
            clusters[groups.find(member.job_id)].append(member)
        for cluster in clusters.values():
            representative = _representative(cluster)
            for member in cluster:
                mapping[member.job_id] = representative
    return mapping
