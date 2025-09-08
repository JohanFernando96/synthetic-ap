from pathlib import Path
import subprocess

from synthap.config.reset import reset_all


def test_reset_all_runs_git(monkeypatch, tmp_path):
    (tmp_path / "catalogs").mkdir()
    (tmp_path / "config").mkdir()

    calls = []

    def fake_run(cmd, check):
        calls.append(cmd)

    monkeypatch.setattr(subprocess, "run", fake_run)

    reset_all(str(tmp_path))

    expected_catalog_checkout = ["git", "checkout", "--", str(tmp_path / "catalogs")]
    expected_catalog_clean = ["git", "clean", "-f", str(tmp_path / "catalogs")]
    expected_config_checkout = ["git", "checkout", "--", str(tmp_path / "config")]
    expected_config_clean = ["git", "clean", "-f", str(tmp_path / "config")]

    assert expected_catalog_checkout in calls
    assert expected_catalog_clean in calls
    assert expected_config_checkout in calls
    assert expected_config_clean in calls
