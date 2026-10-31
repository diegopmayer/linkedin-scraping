from __future__ import annotations

import re

from jobscan.config import RemoteRulesConfig
from jobscan.domain.models import RemoteStatus
from jobscan.domain.text import sentences


def _compile(patterns: list[str]) -> tuple[re.Pattern[str], ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


class RemoteClassifier:
    def __init__(self, rules: RemoteRulesConfig) -> None:
        self.rules_version = rules.rules_version
        self._false_hybrid = re.compile(rules.false_hybrid, re.IGNORECASE)
        self._hybrid = _compile(rules.hybrid)
        self._onsite = _compile(rules.onsite)
        self._remote = _compile(rules.remote)
        self._negations = _compile(rules.negations)
        self._soft_onsite = _compile(rules.soft_onsite)

    def _has(self, patterns: tuple[re.Pattern[str], ...], sentence: str) -> bool:
        return any(p.search(sentence) for p in patterns)

    def classify(self, text: str) -> RemoteStatus:
        hybrid = onsite = remote = False
        for sentence in sentences(text):
            cleaned = self._false_hybrid.sub(" ", sentence)
            negated = self._has(self._negations, cleaned)
            if not negated and self._has(self._hybrid, cleaned):
                hybrid = True
            if not negated and self._has(self._onsite, cleaned) and not self._has(self._soft_onsite, cleaned):
                onsite = True
            if self._has(self._remote, cleaned):
                remote = True
        if hybrid:
            return RemoteStatus.HYBRID
        if onsite and not remote:
            return RemoteStatus.ONSITE
        if remote:
            return RemoteStatus.REMOTE
        return RemoteStatus.UNKNOWN
