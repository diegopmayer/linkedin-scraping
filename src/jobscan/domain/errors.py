from __future__ import annotations


class JobscanError(Exception):
    exit_code = 1


class ConfigError(JobscanError):
    exit_code = 2


class BlockedError(JobscanError):
    exit_code = 3

    def __init__(self, *, url: str, status: int) -> None:
        self.url = url
        self.status = status
        super().__init__(f"stopped after repeated blocking responses (last status {status} on {url})")


class ParseError(JobscanError):
    exit_code = 4

    def __init__(self, message: str, *, url: str = "") -> None:
        self.url = url
        super().__init__(f"{message} ({url})" if url else message)


class MarkupChangedError(ParseError):
    pass


class LockedError(JobscanError):
    exit_code = 5


class LlmError(JobscanError):
    pass
