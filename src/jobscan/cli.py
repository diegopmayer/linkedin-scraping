from __future__ import annotations

import logging
from pathlib import Path

import typer
from dotenv import load_dotenv

from jobscan.adapters.http_client import PoliteFetcher
from jobscan.adapters.llm_classifier import HaikuEligibilityLlm
from jobscan.adapters.store import DuckDbStore
from jobscan.application.collect import Collector, root_specs
from jobscan.application.pipeline import Pipeline, estimate, new_run_id
from jobscan.config import Settings, load_settings
from jobscan.domain.errors import JobscanError

app = typer.Typer(add_completion=False, help="Scan remote US/Canada LinkedIn jobs that accept LATAM candidates.")

ConfigOption = typer.Option(Path("config/searches.yaml"), "--config", "-c", help="Main YAML config file")
RoleOption = typer.Option(None, "--role", help="Limit to role id(s), e.g. data_engineer")
CountryOption = typer.Option(None, "--country", help="Limit to country name(s), e.g. Canada")
UnclearOption = typer.Option(False, "--include-unclear", help="List UNCLEAR jobs in the report")
NoLlmOption = typer.Option(False, "--no-llm", help="Skip the LLM; jobs without a clear restriction become UNCLEAR")


def _setup(config: Path) -> tuple[Settings, DuckDbStore]:
    load_dotenv()
    try:
        settings = load_settings(config)
    except JobscanError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.exit_code) from exc
    logs_dir = settings.path(settings.app.paths.logs_dir)
    logs_dir.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(logs_dir / "jobscan.log", encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    root.addHandler(console)
    return settings, DuckDbStore(settings.path(settings.app.paths.database))


def _pipeline(settings: Settings, store: DuckDbStore, *, no_llm: bool) -> Pipeline:
    def fetcher_factory(run_id: str) -> PoliteFetcher:
        return PoliteFetcher(settings.app.http, store, run_id)

    def llm_factory() -> HaikuEligibilityLlm | None:
        if no_llm or not settings.app.llm.enabled:
            return None
        return HaikuEligibilityLlm(settings.app.llm, store)

    return Pipeline(settings, store, fetcher_factory=fetcher_factory, llm_factory=llm_factory,
                    progress=lambda message: typer.echo(message))


def _validate_filters(settings: Settings, roles: list[str] | None, countries: list[str] | None) -> None:
    unknown_roles = set(roles or []) - set(settings.app.roles)
    known_countries = {c.name for c in settings.app.countries}
    unknown_countries = set(countries or []) - known_countries
    if unknown_roles or unknown_countries:
        typer.secho(
            f"Unknown role(s) {sorted(unknown_roles)} or country(ies) {sorted(unknown_countries)}. "
            f"Roles: {sorted(settings.app.roles)}; countries: {sorted(known_countries)}",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(2)


@app.command()
def run(
    config: Path = ConfigOption,
    resume: bool = typer.Option(False, "--resume", help="Continue the latest paused or failed run"),
    refresh: bool = typer.Option(False, "--refresh", help="Fetch job details again even if stored"),
    role: list[str] = RoleOption,
    country: list[str] = CountryOption,
    include_unclear: bool = UnclearOption,
    no_llm: bool = NoLlmOption,
    dry_run: bool = typer.Option(False, "--dry-run", help="Only fetch the displayed counts and print an estimate"),
) -> None:
    """Count, collect, fetch details, classify and report."""
    settings, store = _setup(config)
    _validate_filters(settings, role, country)
    roles, countries = set(role or []) or None, set(country or []) or None
    if dry_run:
        run_id = new_run_id()
        store.create_run(run_id, mode="count", config_hash=settings.config_hash(), roles=None, countries=None)
        fetcher = PoliteFetcher(settings.app.http, store, run_id)
        counts = Collector(settings, store, fetcher, run_id).count_only(
            root_specs(settings, roles=roles, countries=countries))
        store.update_run(run_id, status="completed", stage="done")
        for item in counts:
            typer.echo(f"{item.role:28} {item.country:15} {item.count.raw if item.count else '?'}")
        typer.echo(estimate(counts, settings).describe())
        raise typer.Exit(0)
    outcome = _pipeline(settings, store, no_llm=no_llm).run(
        resume=resume, refresh=refresh, roles=roles, countries=countries,
        include_unclear=include_unclear or settings.app.report.include_unclear,
    )
    store.close()
    raise typer.Exit(outcome.exit_code)


@app.command()
def count(config: Path = ConfigOption, role: list[str] = RoleOption, country: list[str] = CountryOption) -> None:
    """Fetch only LinkedIn's displayed counts for each search (a few requests)."""
    settings, store = _setup(config)
    _validate_filters(settings, role, country)
    try:
        run_id, counts, out = _pipeline(settings, store, no_llm=True).count(
            roles=set(role or []) or None, countries=set(country or []) or None)
    except JobscanError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.exit_code) from exc
    for item in counts:
        label = settings.app.roles[item.role].label
        typer.echo(f"{label:28} {item.country:15} {item.count.raw if item.count else '?'}")
    typer.echo(f"Saved {out / 'counts.csv'} (run {run_id})")


@app.command()
def report(
    config: Path = ConfigOption,
    run_id: str | None = typer.Option(None, "--run-id", help="Run to report (default: latest)"),
    include_unclear: bool = UnclearOption,
) -> None:
    """Rebuild the report and CSVs from stored data (no requests)."""
    settings, store = _setup(config)
    try:
        out = _pipeline(settings, store, no_llm=True).report(
            run_id, include_unclear=include_unclear or settings.app.report.include_unclear)
    except JobscanError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.exit_code) from exc
    typer.echo(f"Report: {out / 'report.md'}")


@app.command()
def reclassify(
    config: Path = ConfigOption,
    run_id: str | None = typer.Option(None, "--run-id", help="Run to reclassify (default: latest)"),
    include_unclear: bool = UnclearOption,
    no_llm: bool = NoLlmOption,
) -> None:
    """Classify stored descriptions again (after a rules or prompt change). No LinkedIn requests."""
    settings, store = _setup(config)
    try:
        target, out = _pipeline(settings, store, no_llm=no_llm).reclassify(
            run_id, include_unclear=include_unclear or settings.app.report.include_unclear)
    except JobscanError as exc:
        typer.secho(str(exc), fg=typer.colors.RED, err=True)
        raise typer.Exit(exc.exit_code) from exc
    typer.echo(f"Reclassified run {target}. Report: {out / 'report.md'}")


if __name__ == "__main__":
    app()
