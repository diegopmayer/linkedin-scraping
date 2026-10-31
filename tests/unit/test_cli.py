from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from jobscan.cli import app
from tests.conftest import ROOT

runner = CliRunner()


def isolated_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    main = yaml.safe_load((ROOT / "config" / "searches.yaml").read_text(encoding="utf-8"))
    main["paths"].update({"database": str(tmp_path / "db.duckdb"), "reports_dir": str(tmp_path / "reports"),
                          "logs_dir": str(tmp_path / "logs")})
    for name in ("technologies", "eligibility_rules", "remote_rules"):
        main["paths"][name] = str(ROOT / "config" / f"{name}.yaml")
    path = config_dir / "searches.yaml"
    path.write_text(yaml.safe_dump(main), encoding="utf-8")
    return path


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("run", "count", "report", "reclassify"):
        assert command in result.output


def test_report_without_runs_fails_cleanly(tmp_path: Path) -> None:
    result = runner.invoke(app, ["report", "--config", str(isolated_config(tmp_path))])
    assert result.exit_code == 1
    assert "no run found" in result.output


def test_unknown_role_is_rejected_before_any_request(tmp_path: Path) -> None:
    result = runner.invoke(app, ["run", "--config", str(isolated_config(tmp_path)), "--role", "astronaut"])
    assert result.exit_code == 2
    assert "Unknown role" in result.output


def test_bad_config_exits_with_code_2(tmp_path: Path) -> None:
    bad = tmp_path / "config" / "searches.yaml"
    bad.parent.mkdir()
    bad.write_text("time_window: yesterday\n", encoding="utf-8")
    result = runner.invoke(app, ["count", "--config", str(bad)])
    assert result.exit_code == 2
    assert "invalid configuration" in result.output
