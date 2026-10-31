from __future__ import annotations

import pytest

from jobscan.config import Settings
from jobscan.domain.models import RemoteStatus
from jobscan.domain.remote import RemoteClassifier


@pytest.fixture(scope="module")
def classifier(base_settings: Settings) -> RemoteClassifier:
    return RemoteClassifier(base_settings.remote)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("This is a hybrid role: 3 days per week in our Austin office.", RemoteStatus.HYBRID),
        ("Remote role, hybrid, 3 days in office.", RemoteStatus.HYBRID),
        ("USAA roles may offer remote or hybrid flexibility for active-duty military spouses.", RemoteStatus.HYBRID),
        ("Fully remote, not hybrid.", RemoteStatus.REMOTE),
        ("We run a hybrid cloud architecture. This role is remote.", RemoteStatus.REMOTE),
        ("Remote-first team with occasional on-site offsites.", RemoteStatus.REMOTE),
        ("Work on-site in our NYC office.", RemoteStatus.ONSITE),
        ("Relocation to Seattle is required.", RemoteStatus.ONSITE),
        ("Build data pipelines with Spark.", RemoteStatus.UNKNOWN),
        ("", RemoteStatus.UNKNOWN),
    ],
)
def test_remote_status(classifier: RemoteClassifier, text: str, expected: RemoteStatus) -> None:
    assert classifier.classify(text) is expected
