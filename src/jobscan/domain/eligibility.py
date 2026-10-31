from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

from jobscan.config import EligibilityRulesConfig
from jobscan.domain.models import Classification, Eligibility, Method, RuleMatch
from jobscan.domain.text import quote_in_text, sentences

NEGATION_WINDOW = 60
POST_NEGATION_WINDOW = 40


class Verdict(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def confidence(self) -> float: ...
    @property
    def restriction_type(self) -> str: ...
    @property
    def evidence_quotes(self) -> list[str]: ...


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    restriction_type: str
    pattern: re.Pattern[str]


class RestrictionScanner:
    def __init__(self, rules: EligibilityRulesConfig) -> None:
        self.rules_version = rules.rules_version
        self._rules = tuple(
            _Rule(r.id, r.restriction_type, re.compile(r.pattern, 0 if r.case_sensitive else re.IGNORECASE))
            for r in rules.restrictive
        )
        self._negation_before = re.compile(rules.negation_before, re.IGNORECASE)
        self._negation_after = re.compile(rules.negation_after, re.IGNORECASE)
        self._product_context = re.compile(rules.product_context, re.IGNORECASE)
        self._positive = tuple(re.compile(p, re.IGNORECASE) for p in rules.positive_hints)
        self._weak = tuple(re.compile(p, re.IGNORECASE) for p in rules.weak_hints)
        self._stock = tuple(re.compile(p, re.IGNORECASE) for p in rules.stock_text_markers)

    def scan(self, full_text: str) -> list[RuleMatch]:
        matches: list[RuleMatch] = []
        for sentence in sentences(full_text):
            for rule in self._rules:
                found = rule.pattern.search(sentence)
                if found is None:
                    continue
                before = sentence[: found.start()]
                after = sentence[found.end(): found.end() + POST_NEGATION_WINDOW]
                negated = bool(self._negation_before.search(before[-NEGATION_WINDOW:])) or bool(
                    self._negation_after.search(after)
                )
                contextual = sentence.rstrip().endswith("?") or bool(self._product_context.search(before))
                matches.append(RuleMatch(rule.rule_id, rule.restriction_type, sentence, not (negated or contextual)))
        return matches

    def _is_stock(self, sentence: str) -> bool:
        return any(p.search(sentence) for p in self._stock)

    def hints(self, full_text: str, matches: list[RuleMatch]) -> list[str]:
        found: list[str] = [f"possible restriction (not decisive): {m.sentence}" for m in matches if not m.is_clear]
        for sentence in sentences(full_text):
            if any(p.search(sentence) for p in self._positive) and not self._is_stock(sentence):
                found.append(f"mentions LATAM/global hiring words: {sentence}")
            elif any(p.search(sentence) for p in self._weak):
                found.append(f"possible implied restriction: {sentence}")
        return list(dict.fromkeys(found))


def decide(
    *,
    matches: list[RuleMatch],
    verdict: Verdict | None,
    description: str,
    llm_available: bool,
    min_confidence: float,
) -> Classification:
    clear = [m for m in matches if m.is_clear]
    phrase_ids = sorted({m.phrase_id for m in matches})
    if clear:
        return Classification(
            label=Eligibility.US_CA_ONLY,
            method=Method.RULES,
            restriction_type=clear[0].restriction_type,
            evidence=list(dict.fromkeys(m.sentence for m in clear)),
            quotes_verified=True,
            matched_phrases=phrase_ids,
        )
    if not llm_available or verdict is None:
        return Classification(
            label=Eligibility.UNCLEAR,
            method=Method.RULES_FALLBACK,
            restriction_type="none",
            matched_phrases=phrase_ids,
        )

    quotes = [q for q in verdict.evidence_quotes if q.strip()]
    verified = bool(quotes) and all(quote_in_text(q, description) for q in quotes)
    label = Eligibility(verdict.label)
    if label is Eligibility.LATAM_FRIENDLY and (not verified or verdict.confidence < min_confidence):
        label = Eligibility.UNCLEAR
    restriction = verdict.restriction_type if label is Eligibility.US_CA_ONLY else "none"
    if label is Eligibility.US_CA_ONLY and restriction == "none":
        restriction = "residency"
    return Classification(
        label=label,
        method=Method.LLM,
        restriction_type=restriction,
        evidence=quotes,
        quotes_verified=verified,
        confidence=round(float(verdict.confidence), 2),
        matched_phrases=phrase_ids,
    )
