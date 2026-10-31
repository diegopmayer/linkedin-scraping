from __future__ import annotations

import pytest

from jobscan.config import Settings
from jobscan.domain.eligibility import RestrictionScanner
from tests.conftest import FIXTURES


@pytest.fixture(scope="module")
def scanner(base_settings: Settings) -> RestrictionScanner:
    return RestrictionScanner(base_settings.eligibility)


def clear_ids(scanner: RestrictionScanner, text: str) -> set[str]:
    return {m.phrase_id for m in scanner.scan(text) if m.is_clear}


def hint_ids(scanner: RestrictionScanner, text: str) -> set[str]:
    return {m.phrase_id for m in scanner.scan(text) if not m.is_clear}


@pytest.mark.parametrize(
    "text",
    [
        "Must be a US citizen or green card holder.",
        "USC/GC only, no C2C.",
        "This role is not open to candidates outside the US.",
        "Applicants must be authorized to work in the United States.",
        "We are unable to sponsor visas at this time.",
        "This position does not offer visa sponsorship.",
        "No sponsorship available.",
        "Open to residents of the following states: CA, NY, TX.",
        "Must reside in Canada.",
        "Active Secret clearance required.",
        "W2 only. No third parties.",
        "Candidates must be eligible to work in Canada.",
        "We cannot hire outside of the United States.",
        "Remote (US only).",
        "This role requires access to export-controlled technology (ITAR).",
        "Full-time T4 employment.",
        "Must have a valid SSN for the background check.",
        "We participate in E-Verify.",
        "H-1B candidates will not be considered.",
        "Necessário ter visto de trabalho nos EUA.",
        "Debe residir en Estados Unidos.",
    ],
)
def test_clear_restrictions(scanner: RestrictionScanner, text: str) -> None:
    assert clear_ids(scanner, text), text


@pytest.mark.parametrize(
    "text",
    [
        "US citizenship is not required for this role.",
        "You don't need to be a US citizen; we hire contractors across the Americas via Deel.",
        "We hire regardless of citizenship or green card status.",
        "Do we require US citizenship? No.",
        "Our platform helps US citizens file taxes faster.",
    ],
)
def test_negated_or_contextual_restrictions_are_hints_not_decisions(scanner: RestrictionScanner, text: str) -> None:
    assert clear_ids(scanner, text) == set(), text
    assert hint_ids(scanner, text), text


@pytest.mark.parametrize(
    "text",
    [
        "We have offices in São Paulo and customers across LATAM.",
        "We hire contractors across Latin America through Deel.",
        "Graduated from USC with a computer science degree.",
        "You can opt in to our wellness program.",
        "Build data pipelines with Spark and Airflow.",
        "Garbage collection (GC) tuning experience is a plus.",
    ],
)
def test_no_restriction(scanner: RestrictionScanner, text: str) -> None:
    assert clear_ids(scanner, text) == set(), text


def test_restriction_inside_stock_text_still_counts(scanner: RestrictionScanner) -> None:
    text = ("We are an equal opportunity employer and value diversity without regard to race or national origin. "
            "Applicants must be authorized to work in the US.")
    assert "authorized_to_work" in clear_ids(scanner, text)


def test_positive_words_in_stock_text_are_not_hints(scanner: RestrictionScanner) -> None:
    text = "We are an equal opportunity employer and do not discriminate on national origin, including Brazilian."
    hints = scanner.hints(text, scanner.scan(text))
    assert not any("LATAM/global" in h for h in hints)


def test_hints_collect_positive_and_negated(scanner: RestrictionScanner) -> None:
    text = "You don't need to be a US citizen. We hire contractors via Deel. Benefits include a 401k."
    hints = scanner.hints(text, scanner.scan(text))
    assert any("not decisive" in h for h in hints)
    assert any("LATAM/global" in h and "Deel" in h for h in hints)
    assert any("implied" in h and "401k" in h for h in hints)


def test_real_usaa_description_is_restricted(scanner: RestrictionScanner) -> None:
    from jobscan.adapters.linkedin import parse_detail

    detail = parse_detail("4481843507", (FIXTURES / "detail_open.html").read_text(encoding="utf-8"))
    assert clear_ids(scanner, detail.description_text) & {"no_sponsor_verb", "no_sponsorship"}
