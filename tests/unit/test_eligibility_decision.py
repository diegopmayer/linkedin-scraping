from __future__ import annotations

import pytest

from jobscan.config import Settings
from jobscan.domain.eligibility import RestrictionScanner, decide
from jobscan.domain.models import Eligibility, Method
from jobscan.domain.text import quote_in_text
from tests.conftest import FakeVerdict

DEEL = "You don't need to be a US citizen. We hire contractors across the Americas via Deel."


@pytest.fixture(scope="module")
def scanner(base_settings: Settings) -> RestrictionScanner:
    return RestrictionScanner(base_settings.eligibility)


def run(scanner: RestrictionScanner, text: str, verdict: FakeVerdict | None, *, llm: bool = True):
    return decide(matches=scanner.scan(text), verdict=verdict, description=text,
                  llm_available=llm and verdict is not None, min_confidence=0.8)


def test_clear_rule_wins_without_llm(scanner: RestrictionScanner) -> None:
    text = "Must be a US citizen."
    result = run(scanner, text, FakeVerdict("LATAM_FRIENDLY", 0.99, "none", "REMOTE", [text]))
    assert result.label is Eligibility.US_CA_ONLY
    assert result.method is Method.RULES
    assert result.restriction_type == "citizenship"
    assert result.evidence == [text]


def test_llm_path_used_when_no_clear_rule(scanner: RestrictionScanner) -> None:
    verdict = FakeVerdict("LATAM_FRIENDLY", 0.95, "none", "REMOTE",
                          ["We hire contractors across the Americas via Deel."])
    result = run(scanner, DEEL, verdict)
    assert result.label is Eligibility.LATAM_FRIENDLY
    assert result.method is Method.LLM
    assert result.quotes_verified is True
    assert "us_citizen" in result.matched_phrases


def test_fake_quote_downgrades(scanner: RestrictionScanner) -> None:
    verdict = FakeVerdict("LATAM_FRIENDLY", 0.95, "none", "REMOTE", ["We hire anywhere on the planet."])
    result = run(scanner, DEEL, verdict)
    assert result.label is Eligibility.UNCLEAR
    assert result.quotes_verified is False


def test_empty_quotes_downgrade(scanner: RestrictionScanner) -> None:
    result = run(scanner, DEEL, FakeVerdict("LATAM_FRIENDLY", 0.95, "none", "REMOTE", []))
    assert result.label is Eligibility.UNCLEAR


def test_low_confidence_downgrades(scanner: RestrictionScanner) -> None:
    quote = "We hire contractors across the Americas via Deel."
    verdict = FakeVerdict("LATAM_FRIENDLY", 0.6, "none", "REMOTE", [quote])
    assert run(scanner, DEEL, verdict).label is Eligibility.UNCLEAR


def test_llm_off_never_latam(scanner: RestrictionScanner) -> None:
    result = run(scanner, DEEL, None, llm=False)
    assert result.label is Eligibility.UNCLEAR
    assert result.method is Method.RULES_FALLBACK


def test_llm_us_only_accepted_at_any_confidence(scanner: RestrictionScanner) -> None:
    text = "Open to people who live near our Denver office and can visit monthly."
    result = run(scanner, text, FakeVerdict("US_CA_ONLY", 0.4, "office_presence", "REMOTE", []))
    assert result.label is Eligibility.US_CA_ONLY
    assert result.restriction_type == "office_presence"


def test_llm_us_only_without_type_defaults_to_residency(scanner: RestrictionScanner) -> None:
    text = "Silent post."
    result = run(scanner, text, FakeVerdict("US_CA_ONLY", 0.9, "none", "REMOTE", []))
    assert result.restriction_type == "residency"


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("We hire contractors across the Americas via Deel.", True),
        ("  we HIRE contractors   across the americas via deel  ", True),
        ("We hire contractors across the Americas via Deel", True),
        ("We hire", False),
        ("We hire contractors in Europe via Deel.", False),
    ],
)
def test_quote_in_text(quote: str, expected: bool) -> None:
    assert quote_in_text(quote, DEEL) is expected


def test_quote_matches_with_typographic_quotes() -> None:
    assert quote_in_text("You don't need to be a US citizen.", "You don’t need to be a US citizen. More.")
