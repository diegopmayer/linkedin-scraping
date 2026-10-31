from __future__ import annotations

import pytest

from jobscan.config import Settings
from jobscan.domain.roles import RoleMatcher


@pytest.fixture(scope="module")
def matcher(base_settings: Settings) -> RoleMatcher:
    return RoleMatcher(base_settings.app.roles)


@pytest.mark.parametrize(
    ("title", "roles"),
    [
        ("Senior Data Engineer", {"data_engineer"}),
        ("Data Engineer III", {"data_engineer"}),
        ("Sr. Data Engineer (Remote, US)", {"data_engineer"}),
        ("Staff Data Platform Engineer", {"data_engineer"}),
        ("Senior Software Engineer, Data", {"data_engineer"}),
        ("Software Engineer - Data Platform", {"data_engineer"}),
        ("ETL Developer", {"data_engineer"}),
        ("Data Engineering Manager", set()),
        ("Analytics Engineer", set()),
        ("Data Architect", set()),
        ("Software Engineer", set()),
        ("Forward Deployed Engineer", {"forward_deployed_engineer"}),
        ("Forward Deployed Software Engineer", {"forward_deployed_engineer"}),
        ("Forward Deployed AI Engineer", {"forward_deployed_engineer", "ai_engineer"}),
        ("Forward Deployed Strategist", set()),
        ("AI Engineer", {"ai_engineer"}),
        ("Senior Generative AI Engineer", {"ai_engineer"}),
        ("AI/ML Engineer, Senior", {"ai_engineer"}),
        ("Software Engineer (AI)", {"ai_engineer"}),
        ("LLM Engineer", {"ai_engineer"}),
        ("AI Research Engineer", {"ai_engineer"}),
        ("Machine Learning Engineer", set()),
        ("AI Trainer – Remote", set()),
        ("AI Research Scientist", set()),
    ],
)
def test_title_matching(matcher: RoleMatcher, title: str, roles: set[str]) -> None:
    assert matcher.match(title) == roles


def test_ml_engineer_is_boundary_for_ai(matcher: RoleMatcher) -> None:
    assert matcher.boundary_roles("Machine Learning Engineer") == {"ai_engineer"}


def test_software_engineer_is_boundary_for_de(matcher: RoleMatcher) -> None:
    assert "data_engineer" in matcher.boundary_roles("Software Engineer")


def test_solutions_engineer_is_boundary_for_fde(matcher: RoleMatcher) -> None:
    assert matcher.boundary_roles("Solutions Engineer") == {"forward_deployed_engineer"}


def test_matched_title_is_not_boundary(matcher: RoleMatcher) -> None:
    assert matcher.boundary_roles("Senior Data Engineer") == set()
