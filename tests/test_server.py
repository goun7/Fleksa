"""
Tests for Fleksa Web Cockpit & Telemetry Server.
"""

import json
import threading
import time
import urllib.request
import urllib.error
import pytest
from fleksa.server.app import run_server






def test_server_static_assets(live_server):
    # GET /
    res_index = urllib.request.urlopen(f"{live_server}/")
    assert res_index.status == 200
    html_content = res_index.read().decode("utf-8")
    assert "FLEKSA COCKPIT" in html_content
    assert "TEİAŞ Grid" in html_content

    # GET /styles.css
    res_css = urllib.request.urlopen(f"{live_server}/styles.css")
    assert res_css.status == 200
    css_content = res_css.read().decode("utf-8")
    assert "--bg-deep: #06090e" in css_content

    # GET /app.js
    res_js = urllib.request.urlopen(f"{live_server}/app.js")
    assert res_js.status == 200
    js_content = res_js.read().decode("utf-8")
    assert "fetchAndRenderSolve" in js_content


def test_server_api_benchmark(live_server):
    res = urllib.request.urlopen(f"{live_server}/api/benchmark")
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert "dataset_version" in data or "records" in data


def test_server_api_solve(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/solve",
        data=json.dumps({"initial_soc": 250.0, "capacity": 500.0, "max_kw": 250.0}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["status"] == "OPTIMAL"
    assert data["expected_savings_try"] > 0
    assert len(data["hourly"]["hours"]) == 24
    assert len(data["hourly"]["v_term_v"]) == 24
    assert len(data["hourly"]["cell_temp_c"]) == 24
    assert "day_q_loss_pct" in data["degradation"]


def test_server_api_simulate_frequency_event(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/simulate-frequency-event",
        data=json.dumps({"freq_deviation_hz": -0.18}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["compliance"] == "PASS_GRADE_A"
    assert data["response_time_ms"] == 28.0
    assert data["grid_frequency_hz"] == 49.82


def test_server_api_export_credential(live_server):
    res = urllib.request.urlopen(f"{live_server}/api/export-credential")
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert "VerifiableCredential" in data["type"]
    assert data["credentialSubject"]["curtailedEnergyKwh"] == 142.50
    assert "proof" in data


def test_server_openapi_spec(live_server):
    res = urllib.request.urlopen(f"{live_server}/openapi.json")
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["openapi"] == "3.1.0"
    assert "/api/solve" in data["paths"]
    assert "/api/simulate-frequency-event" in data["paths"]
    assert "/api/health" in data["paths"]
    assert "/api/verify-policy" in data["paths"]
    assert "/api/arbitrage-gate" in data["paths"]
    assert "/api/canary/quorum" in data["paths"]
    assert "/api/audit/baseline" in data["paths"]


def test_server_api_health(live_server):
    res = urllib.request.urlopen(f"{live_server}/api/health")
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["status"] == "HEALTHY"
    assert "OpenADR_3.0" in data["standards"]
    assert "benchmark_records_available" in data


def test_server_api_verify_policy(live_server):
    valid_yaml = """
flex_policy:
  version: "2.0.0"
  policy_id: "pol-test-01"
  facility_id: "fac-01"
  created_at: "2026-09-16T00:00:00Z"
  valid_until: "2027-09-16T00:00:00Z"
  assets:
    bess:
      capacity_kwh: 500.0
      max_charge_kw: 250.0
      max_discharge_kw: 250.0
      min_soc_pct: 15.0
      max_soc_pct: 95.0
    compute:
      max_power_kw: 200.0
      min_critical_kw: 50.0
  load_classes: []
  rules: []
  safety_guards:
    fail_closed_on_telemetry_loss: true
"""
    req = urllib.request.Request(
        f"{live_server}/api/verify-policy",
        data=json.dumps({"policy_yaml": valid_yaml, "skip_signature": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["valid"] is True
    assert data["policy_id"] == "pol-test-01"

    # Missing yaml error
    req_bad = urllib.request.Request(
        f"{live_server}/api/verify-policy",
        data=json.dumps({"policy_yaml": ""}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_bad)
    assert exc_info.value.code == 400

    # Invalid invariant yaml
    invalid_yaml = valid_yaml.replace("fail_closed_on_telemetry_loss: true", "fail_closed_on_telemetry_loss: false")
    req_inv = urllib.request.Request(
        f"{live_server}/api/verify-policy",
        data=json.dumps({"policy_yaml": invalid_yaml, "skip_signature": True}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_inv)
    assert exc_info.value.code == 422


def test_server_api_arbitrage_gate(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/arbitrage-gate",
        data=json.dumps({"charge_price": 1.10, "discharge_price": 4.90}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["is_viable"] is True
    assert data["verdict"] == "PROFITABLE_ARBITRAGE"


def test_server_api_canary_quorum(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/canary/quorum",
        data=json.dumps({"epias": 2450.0, "teias": 2420.0, "regional": 2410.0}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert data["consensus_achieved"] is True
    assert "consensus_price_try_kwh" in data

    # Failing divergence
    req_bad = urllib.request.Request(
        f"{live_server}/api/canary/quorum",
        data=json.dumps({"epias": 1000.0, "teias": 4000.0, "regional": 8000.0}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    with pytest.raises(urllib.error.HTTPError) as exc_info:
        urllib.request.urlopen(req_bad)
    assert exc_info.value.code == 409


def test_server_api_audit_baseline(live_server):
    req = urllib.request.Request(
        f"{live_server}/api/audit/baseline",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    res = urllib.request.urlopen(req)
    assert res.status == 200
    data = json.loads(res.read().decode("utf-8"))
    assert len(data["adjusted_baseline_kw"]) == 24
    assert "savings" in data
    assert data["ashrae_compliance"]["is_ashrae_compliant"] is True
    assert len(data["merkle_root"]) == 64


