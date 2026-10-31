from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from jobscan.config import TechConfig
from jobscan.domain.models import TechHit

_LEFT = r"(?<![\w+#.\-/])"
_RIGHT = r"(?![\w+#\-])"
CONTEXT_WINDOW = 80
_SENTENCE_END = re.compile(r"[.!?;\n]")
_CANDIDATE_TERM = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z0-9]*|[A-Za-z][A-Za-z0-9]*(?:DB|SQL|ML|AI|\.js|\.io))\b")


@dataclass(frozen=True)
class _CompiledTech:
    canonical: str
    category: str
    pattern: re.Pattern[str]
    context: re.Pattern[str] | None
    context_only_for_patterns: frozenset[str]


class TechExtractor:
    def __init__(self, techs: Sequence[TechConfig]) -> None:
        self._compiled: list[_CompiledTech] = []
        for tech in techs:
            alternatives = [re.escape(alias) for alias in tech.aliases] + list(tech.patterns)
            if not alternatives:
                continue
            flags = 0 if tech.case_sensitive else re.IGNORECASE
            pattern = re.compile(_LEFT + "(?:" + "|".join(alternatives) + ")" + _RIGHT, flags)
            context = re.compile(tech.context_required, re.IGNORECASE) if tech.context_required else None
            alias_texts = frozenset(alias.lower() for alias in tech.aliases)
            self._compiled.append(_CompiledTech(tech.canonical, tech.category, pattern, context, alias_texts))

    @property
    def canonicals(self) -> list[tuple[str, str]]:
        return [(t.canonical, t.category) for t in self._compiled]

    def _accepted(self, tech: _CompiledTech, text: str, match: re.Match[str]) -> bool:
        if tech.context is None or match.group(0).lower() in tech.context_only_for_patterns:
            return True
        start = max(0, match.start() - CONTEXT_WINDOW)
        end = match.end() + CONTEXT_WINDOW
        before = _SENTENCE_END.split(text[start: match.start()])[-1]
        after = _SENTENCE_END.split(text[match.end(): end])[0]
        return bool(tech.context.search(before + " " + after))

    def unknown_terms(self, text: str) -> set[str]:
        terms: set[str] = set()
        for match in _CANDIDATE_TERM.finditer(text):
            term = match.group(0)
            if not any(tech.pattern.fullmatch(term) for tech in self._compiled):
                terms.add(term)
        return terms

    def extract(self, text: str) -> list[TechHit]:
        hits: list[TechHit] = []
        for tech in self._compiled:
            count = sum(1 for m in tech.pattern.finditer(text) if self._accepted(tech, text, m))
            if count:
                hits.append(TechHit(tech.canonical, tech.category, count))
        return hits
