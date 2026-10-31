from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from jobscan.domain.errors import ConfigError


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_regexes(values: list[str]) -> list[str]:
    for pattern in values:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(f"invalid regex {pattern!r}: {exc}") from exc
    return values


class CountryConfig(_Strict):
    name: str
    location: str


class RoleConfig(_Strict):
    label: str
    keywords: list[str] = Field(min_length=1)
    include: list[str] = Field(min_length=1)
    exclude: list[str] = Field(default_factory=list)
    boundary: list[str] = Field(default_factory=list)

    _validate_include = field_validator("include", "exclude", "boundary")(_check_regexes)


class SlicingConfig(_Strict):
    cap: int = 1000
    dual_sort_on_capped_leaf: bool = True
    sub_locations: bool = False


class HttpConfig(_Strict):
    user_agent: str
    timeout_seconds: float = 30
    min_delay_seconds: float = Field(default=2.0, ge=0)
    max_delay_seconds: float = Field(default=5.0, ge=0)
    backoff_base_seconds: float = Field(default=30, ge=0)
    backoff_max_seconds: float = Field(default=600, ge=0)
    max_consecutive_blocks: int = Field(default=5, ge=1)


class LlmConfig(_Strict):
    enabled: bool = True
    model: str = "claude-haiku-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "low"
    max_tokens: int = Field(default=2048, ge=256)
    min_confidence_latam: float = Field(default=0.8, ge=0, le=1)
    max_calls_per_run: int = Field(default=6000, ge=0)


class ReportConfig(_Strict):
    include_unclear: bool = False
    audit_sample_per_label: int = Field(default=10, ge=0)
    top_technologies: int = Field(default=30, ge=1)


class PathsConfig(_Strict):
    database: str = "data/jobscan.duckdb"
    reports_dir: str = "reports"
    logs_dir: str = "data/logs"
    technologies: str = "config/technologies.yaml"
    eligibility_rules: str = "config/eligibility_rules.yaml"
    remote_rules: str = "config/remote_rules.yaml"


class TechConfig(_Strict):
    canonical: str
    category: str
    aliases: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    context_required: str | None = None
    case_sensitive: bool = False

    _validate_patterns = field_validator("patterns")(_check_regexes)


class TechnologiesConfig(_Strict):
    version: str
    technologies: list[TechConfig] = Field(min_length=1)


class RestrictiveRule(_Strict):
    id: str
    restriction_type: Literal[
        "citizenship", "residency", "work_authorization", "visa", "clearance",
        "employment_type", "location_list", "office_presence",
    ]
    pattern: str
    case_sensitive: bool = False

    @field_validator("pattern")
    @classmethod
    def _valid(cls, value: str) -> str:
        _check_regexes([value])
        return value


class EligibilityRulesConfig(_Strict):
    rules_version: str
    negation_before: str
    negation_after: str
    product_context: str
    restrictive: list[RestrictiveRule] = Field(min_length=1)
    positive_hints: list[str] = Field(default_factory=list)
    weak_hints: list[str] = Field(default_factory=list)
    stock_text_markers: list[str] = Field(default_factory=list)

    _validate_lists = field_validator("positive_hints", "weak_hints", "stock_text_markers")(_check_regexes)


class RemoteRulesConfig(_Strict):
    rules_version: str
    false_hybrid: str
    hybrid: list[str]
    onsite: list[str]
    remote: list[str]
    negations: list[str] = Field(default_factory=list)
    soft_onsite: list[str] = Field(default_factory=list)

    _validate_lists = field_validator("hybrid", "onsite", "remote", "negations", "soft_onsite")(_check_regexes)


class AppConfig(_Strict):
    time_window: str = Field(pattern=r"^r\d+$")
    countries: list[CountryConfig] = Field(min_length=1)
    roles: dict[str, RoleConfig] = Field(min_length=1)
    slicing: SlicingConfig = SlicingConfig()
    http: HttpConfig
    llm: LlmConfig = LlmConfig()
    report: ReportConfig = ReportConfig()
    paths: PathsConfig = PathsConfig()


class Settings(_Strict):
    app: AppConfig
    technologies: TechnologiesConfig
    eligibility: EligibilityRulesConfig
    remote: RemoteRulesConfig
    base_dir: str

    def path(self, relative: str) -> Path:
        candidate = Path(relative)
        return candidate if candidate.is_absolute() else Path(self.base_dir) / candidate

    def config_hash(self) -> str:
        payload = json.dumps(self.model_dump(exclude={"base_dir"}), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _read_yaml(path: Path) -> dict[str, Any]:
    try:
        with path.open(encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError as exc:
        raise ConfigError(f"config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"config file must contain a mapping: {path}")
    return data


def load_settings(config_path: str | Path) -> Settings:
    main_path = Path(config_path).resolve()
    base_dir = main_path.parent.parent if main_path.parent.name == "config" else main_path.parent
    try:
        app = AppConfig.model_validate(_read_yaml(main_path))
        resolve = lambda rel: Path(rel) if Path(rel).is_absolute() else base_dir / rel  # noqa: E731
        return Settings(
            app=app,
            technologies=TechnologiesConfig.model_validate(_read_yaml(resolve(app.paths.technologies))),
            eligibility=EligibilityRulesConfig.model_validate(_read_yaml(resolve(app.paths.eligibility_rules))),
            remote=RemoteRulesConfig.model_validate(_read_yaml(resolve(app.paths.remote_rules))),
            base_dir=str(base_dir),
        )
    except ValidationError as exc:
        raise ConfigError(f"invalid configuration: {exc}") from exc
