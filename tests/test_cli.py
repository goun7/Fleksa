"""
Unit tests for Fleksa CLI.
"""

import pytest
from click.testing import CliRunner
from fleksa.cli.main import main


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(main, ["version"])
    assert result.exit_code == 0
    assert "Fleksa Engine" in result.output


def test_cli_solve():
    runner = CliRunner()
    result = runner.invoke(main, ["solve", "--hours", "12", "--battery-soc", "150"])
    assert result.exit_code == 0
    assert "Optimization Status: OPTIMAL" in result.output
    assert "Expected Savings" in result.output


def test_cli_monte_carlo():
    runner = CliRunner()
    result = runner.invoke(main, ["monte-carlo", "--runs", "100"])
    assert result.exit_code == 0
    assert "Simulation Complete" in result.output
    assert "P50 (Median)" in result.output


def test_cli_verify_policy(tmp_path, ed25519_keypair):
    from tests.test_policy_verifier import create_signed_policy_yaml

    yaml_content = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    policy_file = tmp_path / "test_policy.yaml"
    policy_file.write_text(yaml_content, encoding="utf-8")

    runner = CliRunner()
    # Test with skip-signature since key isn't pre-loaded into default CLI
    result = runner.invoke(main, ["verify-policy", str(policy_file), "--skip-signature"])
    assert result.exit_code == 0
    assert "is valid and all safety guards passed" in result.output

    # Test error handling on bad file
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("invalid_yaml: [", encoding="utf-8")
    res_bad = runner.invoke(main, ["verify-policy", str(bad_file)])
    assert res_bad.exit_code != 0
    assert "Verification failed" in res_bad.output


def test_cli_solve_json_and_benchmark(tmp_path):
    runner = CliRunner()
    result = runner.invoke(main, ["solve", "--hours", "6", "--json-output"])
    assert result.exit_code == 0
    assert '"status": "OPTIMAL"' in result.output

    # Custom benchmark file
    custom_bench = tmp_path / "bench.json"
    custom_bench.write_text('{"records": [{"ptf": 2100, "smf": 2000}]}', encoding="utf-8")
    res_bench = runner.invoke(main, ["solve", "--hours", "4", "--benchmark-file", str(custom_bench)])
    assert res_bench.exit_code == 0


def test_cli_audit():
    runner = CliRunner()
    result = runner.invoke(main, ["audit", "--history-days", "4"])
    assert result.exit_code == 0
    assert "IPMVP Option B Audit Results:" in result.output
    assert "ASHRAE 14 CV(RMSE)" in result.output


def test_cli_canary():
    runner = CliRunner()
    result = runner.invoke(main, ["canary", "--epias", "2500", "--teias", "2480", "--regional", "2450"])
    assert result.exit_code == 0
    assert "Triangulation Canary Quorum Verified" in result.output

    # Failing divergence
    fail_res = runner.invoke(main, ["canary", "--epias", "1000", "--teias", "5000", "--regional", "9000"])
    assert fail_res.exit_code != 0
    assert "Canary consensus rejected" in fail_res.output


def test_cli_arbitrage_gate():
    runner = CliRunner()
    result = runner.invoke(main, ["arbitrage-gate", "--charge", "1.0", "--discharge", "5.0"])
    assert result.exit_code == 0
    assert "Theorem 1 Arbitrage Gate Evaluation" in result.output
    assert "PROFITABLE_ARBITRAGE" in result.output


def test_cli_openadr():
    runner = CliRunner()
    result = runner.invoke(main, ["openadr", "--curtail-kw", "120", "--soc-pct", "70"])
    assert result.exit_code == 0
    assert "OadrCreatedOptEvent" in result.output
    assert "OPT_IN" in result.output


def test_cli_modbus():
    runner = CliRunner()
    result = runner.invoke(main, ["modbus", "--power-pct", "75", "--mode", "CHARGE", "--setpoint-kw", "150"])
    assert result.exit_code == 0
    assert "SunSpec Modbus TCP Generation" in result.output
    assert "ADU Frame" in result.output


def test_cli_credential():
    runner = CliRunner()
    result = runner.invoke(main, ["credential", "--facility-id", "test-facility-01", "--curtailed-kwh", "300"])
    assert result.exit_code == 0
    assert "VerifiableCredential" in result.output
    assert "Cryptographic Verification: PASS" in result.output


def test_cli_benchmark():
    runner = CliRunner()
    result = runner.invoke(main, ["benchmark"])
    assert result.exit_code == 0
    assert "EPIAŞ Benchmark Dataset" in result.output

