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
