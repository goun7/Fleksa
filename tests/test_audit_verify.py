"""
Independent audit-verify integration tests (tests/test_audit_verify.py).

Exercises the `fleksa audit --report` -> `fleksa audit-verify` round-trip:
a generated report must verify, and a tampered report must fail.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_cli(*args, cwd=None):
    env_path = str(ROOT / "src")
    cmd = [sys.executable, "-m", "fleksa", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PYTHONPATH": env_path, "PATH": "/usr/bin:/bin"},
    )


def test_audit_report_verifies(tmp_path):
    report = tmp_path / "report.json"
    gen = _run_cli("audit", "--report", str(report))
    assert gen.returncode == 0, gen.stderr
    assert report.exists()

    verify = _run_cli("audit-verify", str(report))
    assert verify.returncode == 0, verify.stdout + verify.stderr
    assert "VERIFICATION PASSED" in verify.stdout


def test_audit_verify_detects_tampered_savings(tmp_path):
    report = tmp_path / "report.json"
    gen = _run_cli("audit", "--report", str(report))
    assert gen.returncode == 0, gen.stderr

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["claims"]["savings"]["net_financial_savings_try"] = 999999.0
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    verify = _run_cli("audit-verify", str(tampered))
    assert verify.returncode == 1, "tampered report must NOT verify"
    # The verdict is emitted on stderr for machine-parseable failure signalling.
    assert "VERIFICATION FAILED" in verify.stderr


def test_audit_verify_detects_tampered_merkle_root(tmp_path):
    report = tmp_path / "report.json"
    gen = _run_cli("audit", "--report", str(report))
    assert gen.returncode == 0, gen.stderr

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["claims"]["merkle_root"] = "00" * 32
    tampered = tmp_path / "tampered_root.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    verify = _run_cli("audit-verify", str(tampered))
    assert verify.returncode == 1
    assert "merkle_root" in verify.stdout
    # The verdict is emitted on stderr for machine-parseable failure signalling.
    assert "VERIFICATION FAILED" in verify.stderr


def test_audit_report_records_inputs_and_claims(tmp_path):
    report = tmp_path / "report.json"
    gen = _run_cli("audit", "--report", str(report))
    assert gen.returncode == 0, gen.stderr

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["report_version"] == 1
    for key in ("history_days", "actual_meter_kw", "ptf_tariff_try_kwh", "event_hours"):
        assert key in payload["inputs"]
    assert len(payload["inputs"]["actual_meter_kw"]) == 24
    assert "merkle_root" in payload["claims"]
    # The new materiality disclosure must be present and non-negative.
    assert payload["claims"]["out_of_window_curtailed_kwh"] >= 0.0


def _verify_line_count(report_path):
    """Return (n_checks, n_pass) parsed from an audit-verify run."""
    res = _run_cli("audit-verify", str(report_path))
    marks = [ln for ln in res.stdout.splitlines()
             if ln.strip().startswith(("✓", "✗")) and "claim=" in ln]
    n_pass = sum(1 for ln in marks if ln.strip().startswith("✓"))
    return len(marks), n_pass, res


def test_audit_verify_runs_at_least_12_checks(tmp_path):
    """The honest-boundary expansion: 9 checks -> 12+ independent checks."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0
    n_checks, n_pass, res = _verify_line_count(report)
    assert res.returncode == 0, res.stdout + res.stderr
    assert n_checks >= 12, f"expected >=12 checks, got {n_checks}"
    assert n_checks == n_pass


def test_audit_verify_detects_tampered_out_of_window(tmp_path):
    """Inflating claimed savings via an out-of-window loophole must fail."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["claims"]["out_of_window_curtailed_kwh"] = 999999.0
    tampered = tmp_path / "tampered_oow.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    n_checks, n_pass, res = _verify_line_count(tampered)
    assert res.returncode == 1, "tampered materiality claim must NOT verify"
    assert "out_of_window" in res.stdout
    assert n_pass < n_checks


def test_audit_verify_detects_tampered_threshold(tmp_path):
    """Loosening a reported statistical threshold must be caught."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["claims"]["ashrae"]["cv_rmse_threshold_pct"] = 0.01
    tampered = tmp_path / "tampered_thr.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    n_checks, n_pass, res = _verify_line_count(tampered)
    assert res.returncode == 1
    assert "cv_rmse_threshold" in res.stdout


def test_audit_verify_detects_truncated_actual_meter(tmp_path):
    """A truncated meter series changes the recomputation and must fail."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["inputs"]["actual_meter_kw"] = payload["inputs"]["actual_meter_kw"][:20]
    tampered = tmp_path / "tampered_trunc.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    res = _run_cli("audit-verify", str(tampered))
    assert res.returncode == 1


def test_audit_verify_detects_negative_tariff(tmp_path):
    """A negative tariff makes savings absurd; structural check must catch it."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["inputs"]["ptf_tariff_try_kwh"][0] = -100.0
    tampered = tmp_path / "tampered_neg.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    res = _run_cli("audit-verify", str(tampered))
    assert res.returncode == 1
    assert "tariff_non_negative" in res.stdout


def test_audit_verify_detects_version_rollback(tmp_path):
    """A report_version other than 1 is a schema mismatch."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    payload["report_version"] = 0
    tampered = tmp_path / "tampered_ver.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    res = _run_cli("audit-verify", str(tampered))
    assert res.returncode == 1
    assert "report_version" in res.stdout


def test_audit_verify_detects_missing_event_hours(tmp_path):
    """Removing the event_hours input must abort with exit 2, not verify."""
    report = tmp_path / "report.json"
    assert _run_cli("audit", "--report", str(report)).returncode == 0

    payload = json.loads(report.read_text(encoding="utf-8"))
    del payload["inputs"]["event_hours"]
    tampered = tmp_path / "tampered_missing.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")

    res = _run_cli("audit-verify", str(tampered))
    assert res.returncode == 2
