"""
Comprehensive edge-case and branch coverage suite for Fleksa.
Targets 100% test coverage across all modules.
"""

import json
import pytest
import yaml
import urllib.request
from datetime import datetime

from fleksa.policy.verifier import FlexPolicyVerifier
from fleksa.policy.schema import FlexPolicyEnvelope, FlexPolicyDocument
from fleksa.core.errors import PolicyVerificationError, SafetyGuardViolationError
from fleksa.battery.degradation import BatteryDegradationEngine
from fleksa.market.feeds import EpiasDataParser, MarketPricePoint
from fleksa.market.canary import TriangulationCanary
from fleksa.core.errors import ByzantinePriceFeedError
from fleksa.workload.speculative import DynamicSpeculativeOptimizer
from fleksa.audit.baseline import IpmvpBaselineEngine



def test_policy_verifier_edge_cases():
    verifier = FlexPolicyVerifier()

    # 1. Invalid YAML / non-dict
    with pytest.raises(PolicyVerificationError, match="YAML parsing error|schema validation error"):
        verifier.parse_and_validate(": invalid : yaml : [", verify_signature=False)

    # 2. Invalid schema (missing required fields)
    with pytest.raises(PolicyVerificationError, match="schema validation error"):
        verifier.parse_and_validate("flex_policy: {version: '2.0.0'}", verify_signature=False)

    # 3. Policy with complex conditions: gt, lt, gte, lte, and missing telemetry
    policy_dict = {
        "flex_policy": {
            "version": "2.0.0",
            "policy_id": "pol-complex-01",
            "facility_id": "fac-01",
            "created_at": "2026-09-16T12:00:00Z",
            "valid_until": "2026-12-31T23:59:59Z",
            "assets": {
                "bess": {
                    "capacity_kwh": 500.0,
                    "max_charge_kw": 250.0,
                    "max_discharge_kw": 250.0,
                    "min_soc_pct": 15.0,
                    "max_soc_pct": 95.0,
                    "max_daily_cycles": 1.5,
                    "chemistry": "LFP",
                },
                "compute": {
                    "max_power_kw": 400.0,
                    "min_critical_kw": 100.0,
                    "gpu_nodes_count": 32,
                    "allow_dvfs_capping": True,
                },
            },
            "load_classes": [
                {"id": "class-0", "priority": 0, "interruptible": False}
            ],
            "rules": [
                {
                    "id": "rule-complex",
                    "condition": {
                        "and": [
                            {"ptf": {"gt": 3.0, "lt": 10.0, "gte": 3.5, "lte": 9.5}},
                            {"missing_metric": {"gt": 1.0}}
                        ]
                    },
                    "actions": [{"target": "bess", "command": "hold"}],
                    "audit_note": "Complex bounds test"
                }
            ],
            "safety_guards": {
                "fail_closed_on_telemetry_loss": True,
                "telemetry_timeout_sec": 90.0,
                "max_grid_export_limit_kw": 0.0,
                "human_in_the_loop_triggers": ["thermal_trip"],
            },
        }
    }

    yaml_str = yaml.safe_dump(policy_dict)
    policy = verifier.parse_and_validate(yaml_str, verify_signature=False)

    # Missing metric branch (lines 100-101 in verifier.py)
    actions = verifier.evaluate_rules(policy, {"ptf": 5.0})
    assert len(actions) == 0

    # lt failure branch (line 107)
    actions_high = verifier.evaluate_rules(policy, {"ptf": 11.0, "missing_metric": 2.0})
    assert len(actions_high) == 0

    # lte failure branch (line 111)
    actions_high2 = verifier.evaluate_rules(policy, {"ptf": 9.8, "missing_metric": 2.0})
    assert len(actions_high2) == 0

    # gte failure branch (line 109)
    actions_low = verifier.evaluate_rules(policy, {"ptf": 3.2, "missing_metric": 2.0})
    assert len(actions_low) == 0

    # Complete match
    actions_match = verifier.evaluate_rules(policy, {"ptf": 5.0, "missing_metric": 2.0})
    assert len(actions_match) == 1

    # Signature verification on unsigned policy
    with pytest.raises(PolicyVerificationError, match="Missing required crypto_signature block"):
        verifier.parse_and_validate(yaml_str, verify_signature=True)

    # Signature verification with unknown key
    policy_dict["flex_policy"]["crypto_signature"] = {
        "key_id": "unknown-key",
        "algorithm": "Ed25519",
        "sig": "01" * 64
    }
    with pytest.raises(PolicyVerificationError, match="Unknown or untrusted"):
        verifier.parse_and_validate(yaml.safe_dump(policy_dict), verify_signature=True)



def test_battery_degradation_piecewise_and_temperature_penalty():
    engine = BatteryDegradationEngine()

    # DoD piecewise: 35% DoD
    cost_35 = engine.marginal_cost_per_kwh(depth_of_discharge_pct=35.0, cell_temp_celsius=25.0)
    assert cost_35 == 0.32

    # Temperature penalty (> 30C)
    cost_hot = engine.marginal_cost_per_kwh(depth_of_discharge_pct=35.0, cell_temp_celsius=35.0)
    assert cost_hot > cost_35

    # Extreme DoD (> 80%)
    cost_deep = engine.marginal_cost_per_kwh(depth_of_discharge_pct=90.0)
    assert cost_deep >= 1.35


def test_market_feeds_unrecognized_direction():
    raw_items = [
        {"date": "2026-09-16T12:00:00Z", "price": 2500.0, "direction": "NON_EXISTENT_DIRECTION"}
    ]
    points = EpiasDataParser.parse_hourly_prices(raw_items)
    assert len(points) == 1
    assert points[0].system_direction.value == "BALANCED"


def test_triangulation_canary_byzantine_rejection():
    canary = TriangulationCanary(max_allowed_divergence_pct=35.0)

    # Valid consensus
    accepted = canary.verify_price_quorum(epias_price=2500.0, teias_price=2520.0, regional_proxy_price=2480.0)
    assert accepted == 2500.0

    # Outlier price (> 15000)
    with pytest.raises(ByzantinePriceFeedError, match="Implausible price outlier detected"):
        canary.verify_price_quorum(epias_price=2500.0, teias_price=2520.0, regional_proxy_price=99999.0)

    # Negative outlier (< -500)
    with pytest.raises(ByzantinePriceFeedError, match="Implausible price outlier detected"):
        canary.verify_price_quorum(epias_price=-600.0, teias_price=2520.0, regional_proxy_price=2500.0)



def test_baseline_pre_event_adjustment_cap():
    base_curve = [100.0] * 24
    adj_curve = IpmvpBaselineEngine.apply_same_day_adjustment(
        baseline_hourly_kw=base_curve,
        pre_event_actual_2h_kw=[200.0, 200.0],
        event_start_hour=14,
        max_adjustment_fraction=0.20
    )
    assert adj_curve[14] == pytest.approx(120.0, abs=0.1)


def test_speculative_scheduler_bounds():
    # 1. Super-peak (> 4.50)
    opt_eco = DynamicSpeculativeOptimizer.optimize_parameters(ptf_try_kwh=5.20)
    assert opt_eco["operating_mode"] == "ECO_CONSERVE"
    assert opt_eco["draft_length"] == 2

    # 2. Moderate peak (> 3.00, hits line 32)
    opt_bal = DynamicSpeculativeOptimizer.optimize_parameters(ptf_try_kwh=3.80)
    assert opt_bal["operating_mode"] == "BALANCED"
    assert opt_bal["draft_length"] == 3

    # 3. Off-peak (<= 3.00)
    opt_max = DynamicSpeculativeOptimizer.optimize_parameters(ptf_try_kwh=1.80, base_draft_length=6)
    assert opt_max["operating_mode"] == "MAX_THROUGHPUT"
    assert opt_max["draft_length"] == 6



def test_server_routes_options_and_errors(live_server):
    req_opt = urllib.request.Request(f"{live_server}/api/solve", method="OPTIONS")
    res_opt = urllib.request.urlopen(req_opt)
    assert res_opt.status == 204

    try:
        urllib.request.urlopen(f"{live_server}/non-existent-endpoint")
    except urllib.error.HTTPError as e:
        assert e.code == 404

    try:
        req_post = urllib.request.Request(
            f"{live_server}/api/unknown-post",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req_post)
    except urllib.error.HTTPError as e:
        assert e.code == 404


import numpy as np


def test_baseline_event_start_zero():
    base = np.array([100.0] * 24)
    res = IpmvpBaselineEngine.apply_same_day_adjustment(
        baseline_hourly_kw=base,
        pre_event_actual_2h_kw=np.array([100.0, 100.0]),
        event_start_hour=0
    )
    assert np.array_equal(res, base)


def test_modbus_edge_cases():
    from fleksa.protocols.modbus import SunSpecInverterMapper
    import struct

    # Line 39: DISCHARGE mode
    cmd = SunSpecInverterMapper.encode_command(100.0, "DISCHARGE", 50.0)
    assert cmd[40084] == 2

    # Line 93: Empty registers raises ValueError
    with pytest.raises(ValueError, match="No registers provided"):
        SunSpecInverterMapper.build_modbus_tcp_write_frame({})

    # Line 119: Response too short
    with pytest.raises(ValueError, match="too short"):
        SunSpecInverterMapper.parse_modbus_tcp_response(b"short")

    # Line 123-124: Exception code
    exc_frame = struct.pack(">HHHBB", 1, 0, 3, 1, 0x90) + b"\x02" + b"\x00" * 10
    with pytest.raises(ValueError, match="Modbus Exception Response"):
        SunSpecInverterMapper.parse_modbus_tcp_response(exc_frame)


def test_attestation_edge_cases():
    from fleksa.protocols.attestation import W3cAttestationBuilder

    # Line 66: Wrong proof type
    bad_type = {"proof": {"type": "WrongSignature"}}
    assert not W3cAttestationBuilder.verify_credential(bad_type, "01" * 32)

    # Line 70: Missing proofValue
    bad_sig = {"proof": {"type": "Ed25519Signature2020"}}
    assert not W3cAttestationBuilder.verify_credential(bad_sig, "01" * 32)


def test_policy_verifier_invalid_key_or_sig():
    verifier = FlexPolicyVerifier()
    with pytest.raises(PolicyVerificationError, match="requires valid key_id and sig"):
        verifier._verify_signature({"crypto_signature": {"key_id": "", "sig": ""}})


def test_solver_infeasible_raises_convergence_error():
    from fleksa.mpc.solver import FleksaMPCSolver
    from fleksa.core.types import FacilityState, MarketDataHorizon
    from fleksa.core.errors import OptimizationConvergenceError

    # Contradictory bounds: min_soc_pct > max_soc_pct to force solver failure
    state = FacilityState(
        bess_soc_kwh=250.0,
        bess_capacity_kwh=500.0,
        bess_max_kw=250.0,
        min_soc_pct=0.99,
        max_soc_pct=0.01,  # Impossible!
    )
    horizon = MarketDataHorizon(
        hours=24,
        ptf_try_kwh=np.array([2.0] * 24),
        base_load_kw=np.array([100.0] * 24),
        pv_gen_kw=np.array([0.0] * 24),
        ambient_temp_c=np.array([20.0] * 24),
        smf_try_kwh=np.array([2.0] * 24)
    )
    solver = FleksaMPCSolver(state, horizon)
    with pytest.raises(OptimizationConvergenceError):
        solver.solve()


def test_cli_additional_edge_cases(monkeypatch, tmp_path):
    from click.testing import CliRunner
    from fleksa.cli.main import main
    import runpy

    runner = CliRunner()

    # 1. Verification failure branch (lines 77-79 in main.py)
    bad_policy = tmp_path / "bad.yaml"
    bad_policy.write_text("invalid: [yaml: foo")
    result_fail = runner.invoke(main, ["verify-policy", str(bad_policy)])
    assert result_fail.exit_code != 0
    assert "Verification failed" in result_fail.output

    # 2. UI command invocation (lines 110-112)
    called = []
    def fake_run_server(port, bind_address):
        called.append((port, bind_address))

    monkeypatch.setattr("fleksa.server.app.run_server", fake_run_server)
    res_ui = runner.invoke(main, ["ui", "--port", "8888", "--host", "0.0.0.0"])
    assert res_ui.exit_code == 0
    assert called == [(8888, "0.0.0.0")]

    # 3. Main module entrypoints test
    import sys
    monkeypatch.setattr(sys, "argv", ["fleksa", "--help"])
    sys.modules.pop("fleksa.__main__", None)
    try:
        runpy.run_module("fleksa", run_name="__main__")
    except SystemExit:
        pass

    sys.modules.pop("fleksa.cli.main", None)
    try:
        runpy.run_module("fleksa.cli.main", run_name="__main__")
    except SystemExit:
        pass

    # Loopback HTTPServer to prevent port binding collision
    class LoopbackHttpServer:
        def __init__(self, addr, handler):
            pass
        def serve_forever(self):
            pass

    monkeypatch.setattr("http.server.HTTPServer", LoopbackHttpServer)
    sys.modules.pop("fleksa.server.app", None)
    runpy.run_module("fleksa.server.app", run_name="__main__")


def test_server_additional_edge_cases(live_server, monkeypatch, tmp_path):
    from fleksa.server import app

    # 1. Post malformed JSON body to /api/solve (lines 66-67)
    req = urllib.request.Request(
        f"{live_server}/api/solve",
        data=b"invalid-not-json",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200

    # 2. Benchmark file not found fallback on get_benchmark (line 90)
    fake_path = tmp_path / "does_not_exist.json"
    monkeypatch.setattr(app, "BENCHMARK_PATH", fake_path)
    res_bench = urllib.request.urlopen(f"{live_server}/api/benchmark")
    assert res_bench.status == 200
    data = json.loads(res_bench.read().decode("utf-8"))
    assert data == {"records": []}

    # 3. Benchmark missing during solve (lines 106-107)
    req_solve = urllib.request.Request(
        f"{live_server}/api/solve",
        data=b"{}",
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    res_solve = urllib.request.urlopen(req_solve)
    assert res_solve.status == 200

    # 4. Serve static file not found (lines 79-81)
    handler = app.FleksaAPIHandler
    non_existent = tmp_path / "missing.txt"
    class DummyHandler:
        def __init__(self):
            self.headers_set = []
            self.written = b""
        def _set_headers(self, mime, status):
            self.headers_set.append((mime, status))
        class WFile:
            def __init__(self, parent):
                self.parent = parent
            def write(self, b):
                self.parent.written += b
        @property
        def wfile(self):
            return self.WFile(self)

    d = DummyHandler()
    app.FleksaAPIHandler._serve_static(d, non_existent, "text/plain")
    assert d.headers_set == [("text/plain", 404)]
    assert d.written == b"File not found"

    # 5. Corrupt benchmark in _handle_get_health (lines 106-107)
    corrupt_bench = tmp_path / "corrupt.json"
    corrupt_bench.write_text("{not-valid-json", encoding="utf-8")
    monkeypatch.setattr(app, "BENCHMARK_PATH", corrupt_bench)
    d_health = DummyHandler()
    app.FleksaAPIHandler._handle_get_health(d_health)
    health_res = json.loads(d_health.written.decode("utf-8"))
    assert health_res["benchmark_records_available"] == 0


def test_cli_remaining_branches(tmp_path, monkeypatch):
    import runpy
    from click.testing import CliRunner
    from fleksa.cli.main import main

    runner = CliRunner()

    # 1. Short benchmark padding (lines 73-74)
    short_bench = tmp_path / "short_bench.json"
    short_bench.write_text('{"records": [{"ptf": 2000}]}', encoding="utf-8")
    res1 = runner.invoke(main, ["solve", "--hours", "10", "--benchmark-file", str(short_bench)])
    assert res1.exit_code == 0

    # 2. Corrupt benchmark record fallback (line 76)
    bad_bench = tmp_path / "bad_bench.json"
    bad_bench.write_text('{"records": [{"no_ptf": 123}]}', encoding="utf-8")
    res2 = runner.invoke(main, ["solve", "--hours", "6", "--benchmark-file", str(bad_bench)])
    assert res2.exit_code == 0

    # 3. Empty benchmark records padding
    empty_records_bench = tmp_path / "empty_bench.json"
    empty_records_bench.write_text('{"records": []}', encoding="utf-8")
    res3 = runner.invoke(main, ["solve", "--hours", "4", "--benchmark-file", str(empty_records_bench)])
    assert res3.exit_code == 0

    # 4. Benchmark file does not exist branch (line 76 & lines 398-399)
    from fleksa.cli import main as cli_mod
    monkeypatch.setattr(cli_mod, "DEFAULT_BENCHMARK_PATH", tmp_path / "non_existent.json")
    res_no_bench = runner.invoke(main, ["solve", "--hours", "12"])
    assert res_no_bench.exit_code == 0

    res_bench_missing = runner.invoke(main, ["benchmark"])
    assert res_bench_missing.exit_code == 0
    assert "Benchmark file not found" in res_bench_missing.output

    # 5. cli/main.py __main__ block
    import sys
    monkeypatch.setattr(sys, "argv", ["fleksa", "version"])
    sys.modules.pop("fleksa.cli.main", None)
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_module("fleksa.cli.main", run_name="__main__")
    assert exit_info.value.code == 0





