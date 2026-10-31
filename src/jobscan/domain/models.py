from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from enum import Enum


class RemoteStatus(str, Enum):
    REMOTE = "REMOTE"
    HYBRID = "HYBRID"
    ONSITE = "ONSITE"
    UNKNOWN = "UNKNOWN"


class Eligibility(str, Enum):
    LATAM_FRIENDLY = "LATAM_FRIENDLY"
    US_CA_ONLY = "US_CA_ONLY"
    UNCLEAR = "UNCLEAR"


class Method(str, Enum):
    RULES = "rules"
    LLM = "llm"
    RULES_FALLBACK = "rules-fallback"


RESTRICTION_TYPES = (
    "citizenship", "residency", "work_authorization", "visa", "clearance",
    "employment_type", "location_list", "office_presence", "none",
)


@dataclass(frozen=True)
class DisplayedCount:
    raw: str
    value: int | None
    is_lower_bound: bool


@dataclass(frozen=True)
class SliceSpec:
    role: str
    country: str
    keywords: str
    location: str
    time_window: str
    f_e: str | None = None
    f_jt: str | None = None
    sort_by: str | None = None
    depth: int = 0

    def filters(self) -> dict[str, str | None]:
        return {
            "keywords": self.keywords, "location": self.location, "f_TPR": self.time_window,
            "f_E": self.f_e, "f_JT": self.f_jt, "sortBy": self.sort_by,
        }

    def slice_id(self, run_id: str) -> str:
        payload = json.dumps({"run": run_id, "role": self.role, **self.filters()}, sort_keys=True)
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:20]


@dataclass(frozen=True)
class JobCard:
    job_id: str
    title: str
    company: str
    location_text: str
    posted_at: str | None
    url: str
    company_url: str | None = None


@dataclass(frozen=True)
class JobDetail:
    job_id: str
    title: str
    description_html: str
    description_text: str
    seniority: str | None
    employment_type: str | None
    job_function: str | None
    industries: str | None
    applicants_text: str | None
    is_closed: bool


@dataclass(frozen=True)
class RuleMatch:
    phrase_id: str
    restriction_type: str
    sentence: str
    is_clear: bool


@dataclass(frozen=True)
class TechHit:
    canonical: str
    category: str
    mention_count: int


@dataclass(frozen=True)
class Classification:
    label: Eligibility
    method: Method
    restriction_type: str
    evidence: list[str] = field(default_factory=list)
    quotes_verified: bool = False
    confidence: float | None = None
    matched_phrases: list[str] = field(default_factory=list)

    def as_row(self) -> dict[str, object]:
        row = asdict(self)
        row["label"] = self.label.value
        row["method"] = self.method.value
        return row
