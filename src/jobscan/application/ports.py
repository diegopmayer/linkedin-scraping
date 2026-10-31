from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FetchResult:
    url: str
    status: int
    body: str
    from_cache: bool = False


class Fetcher(Protocol):
    request_count: int

    def get(self, url: str, *, cache_scope: str, force: bool = False) -> FetchResult: ...


class LlmVerdictLike(Protocol):
    @property
    def label(self) -> str: ...
    @property
    def confidence(self) -> float: ...
    @property
    def restriction_type(self) -> str: ...
    @property
    def work_arrangement(self) -> str: ...
    @property
    def evidence_quotes(self) -> list[str]: ...
    @property
    def reasoning_short(self) -> str: ...


class EligibilityLlm(Protocol):
    @property
    def model(self) -> str: ...
    @property
    def prompt_version(self) -> str: ...

    def classify(
        self, *, title: str, location: str, description: str, hints: list[str]
    ) -> LlmVerdictLike | None: ...
