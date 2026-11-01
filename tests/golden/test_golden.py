from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pytest
import yaml
from dotenv import load_dotenv

from jobscan.adapters.llm_classifier import HaikuEligibilityLlm
from jobscan.adapters.store import DuckDbStore
from jobscan.config import Settings
from jobscan.domain.eligibility import RestrictionScanner, decide
from jobscan.domain.models import Eligibility

GOLDEN = Path(__file__).resolve().parent / "cases.yaml"
MIN_CASES = 30
REQUIRED_MIX = {"explicit": 8, "implied": 6, "negated_or_misleading": 4, "latam_friendly": 6, "silent": 4,
                "stock_text": 2}


def load_cases() -> list[dict[str, Any]]:
    return list(yaml.safe_load(GOLDEN.read_text(encoding="utf-8"))["cases"])


CASES = load_cases()


@pytest.fixture(scope="module")
def scanner(base_settings: Settings) -> RestrictionScanner:
    return RestrictionScanner(base_settings.eligibility)


def test_golden_set_size_and_mix() -> None:
    assert len(CASES) >= MIN_CASES
    assert len({c["id"] for c in CASES}) == len(CASES)
    mix = Counter(c["category"] for c in CASES)
    for category, minimum in REQUIRED_MIX.items():
        assert mix[category] >= minimum, category


def test_real_cases_present() -> None:
    real = [c for c in CASES if not c.get("synthetic", True)]
    if len(real) < MIN_CASES:
        pytest.skip(f"only {len(real)} real labelled descriptions; add {MIN_CASES - len(real)} from a run (FR4.8)")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_rules_decide_only_where_expected(scanner: RestrictionScanner, case: dict[str, Any]) -> None:
    clear = [m for m in scanner.scan(case["description"]) if m.is_clear]
    if case["rules"] == "US_CA_ONLY":
        assert clear, f"rules missed a clear restriction in {case['id']}"
    else:
        assert not clear, f"rules wrongly excluded {case['id']}: {[m.phrase_id for m in clear]}"


@pytest.mark.parametrize("case", [c for c in CASES if c["expected"] != "US_CA_ONLY"],
                         ids=[c["id"] for c in CASES if c["expected"] != "US_CA_ONLY"])
def test_rules_never_exclude_non_restricted(scanner: RestrictionScanner, case: dict[str, Any]) -> None:
    assert not any(m.is_clear for m in scanner.scan(case["description"]))


@pytest.mark.llm
def test_full_eligibility_with_llm(base_settings: Settings, scanner: RestrictionScanner, tmp_path: Path) -> None:
    load_dotenv(Path(base_settings.base_dir) / ".env")
    cache_path = Path(base_settings.base_dir) / "data" / "golden_llm_cache.duckdb"
    store = DuckDbStore(cache_path)
    llm = HaikuEligibilityLlm(base_settings.app.llm.model_copy(update={"enabled": True}), store)
    results: dict[str, Eligibility] = {}
    for case in CASES:
        text = case["description"]
        matches = scanner.scan(text)
        verdict = None
        if not any(m.is_clear for m in matches):
            verdict = llm.classify(title="", location="United States", description=text,
                                   hints=scanner.hints(text, matches))
            assert llm.disabled_reason is None, llm.disabled_reason
        results[case["id"]] = decide(matches=matches, verdict=verdict, description=text,
                                     llm_available=verdict is not None,
                                     min_confidence=base_settings.app.llm.min_confidence_latam).label
    store.close()

    restricted = [c["id"] for c in CASES if c["expected"] == "US_CA_ONLY"]
    leaks = [cid for cid in restricted if results[cid] is Eligibility.LATAM_FRIENDLY]
    missed = [cid for cid in restricted if results[cid] is not Eligibility.US_CA_ONLY]
    false_latam = [c["id"] for c in CASES
                   if c["expected"] != "LATAM_FRIENDLY" and results[c["id"]] is Eligibility.LATAM_FRIENDLY]
    latam_found = [c["id"] for c in CASES
                   if c["expected"] == "LATAM_FRIENDLY" and results[c["id"]] is Eligibility.LATAM_FRIENDLY]
    summary = {cid: label.value for cid, label in results.items()}
    assert not leaks, f"US/CA-only cases labelled LATAM_FRIENDLY: {leaks}\n{summary}"
    assert not missed, f"restriction cases not labelled US_CA_ONLY: {missed}\n{summary}"
    assert not false_latam, f"non-LATAM cases labelled LATAM_FRIENDLY: {false_latam}\n{summary}"
    print(f"LATAM recall: {len(latam_found)}/{sum(c['expected'] == 'LATAM_FRIENDLY' for c in CASES)}")
