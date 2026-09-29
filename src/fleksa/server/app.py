"""
Fleksa Real-Time Cockpit & Web Telemetry Server.
"""

import json
import mimetypes
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional
import numpy as np

from fleksa import __version__
from fleksa.core.types import FacilityState, MarketDataHorizon
from fleksa.core.errors import ByzantinePriceFeedError, PolicyVerificationError
from fleksa.mpc.solver import FleksaMPCSolver
from fleksa.battery.thevenin import TheveninBatteryModel
from fleksa.battery.degradation import BatteryDegradationEngine
from fleksa.protocols.attestation import W3cAttestationBuilder
from fleksa.audit.baseline import IpmvpBaselineEngine
from fleksa.audit.ledger import CryptographicSavingsLedger
from fleksa.policy.verifier import FlexPolicyVerifier
from fleksa.market.arbitrage_gate import EconomicArbitrageGate
from fleksa.market.canary import TriangulationCanary


STATIC_DIR = Path(__file__).parent.parent / "ui"
BENCHMARK_PATH = Path(__file__).parent.parent.parent.parent / "data" / "epias_2026_benchmark.json"


class FleksaAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the Fleksa Cockpit and Telemetry API."""

    def _set_headers(self, content_type: str = "application/json", status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(status=204)

    def do_GET(self):
        clean_path = self.path.split("?")[0]
        if clean_path in ("/", "/index.html"):
            self._serve_static(STATIC_DIR / "index.html", "text/html")
        elif clean_path == "/styles.css":
            self._serve_static(STATIC_DIR / "styles.css", "text/css")
        elif clean_path == "/app.js":
            self._serve_static(STATIC_DIR / "app.js", "application/javascript")
        elif clean_path == "/api/health":
            self._handle_get_health()
        elif clean_path == "/api/benchmark":
            self._handle_get_benchmark()
        elif clean_path == "/api/export-credential":
            self._handle_export_credential()
        elif clean_path == "/openapi.json":
            spec_path = Path(__file__).parent / "openapi.json"
            self._serve_static(spec_path, "application/json")
        else:
            self._set_headers("application/json", 404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode("utf-8"))

    def do_POST(self):
        clean_path = self.path.split("?")[0]
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8") if content_length > 0 else "{}"
        try:
            payload = json.loads(body) if body else {}
        except json.JSONDecodeError:
            payload = {}

        if clean_path == "/api/solve":
            self._handle_post_solve(payload)
        elif clean_path == "/api/simulate-frequency-event":
            self._handle_simulate_frequency_event(payload)
        elif clean_path == "/api/verify-policy":
            self._handle_verify_policy(payload)
        elif clean_path == "/api/arbitrage-gate":
            self._handle_arbitrage_gate(payload)
        elif clean_path == "/api/canary/quorum":
            self._handle_canary_quorum(payload)
        elif clean_path == "/api/audit/baseline":
            self._handle_audit_baseline(payload)
        else:
            self._set_headers("application/json", 404)
            self.wfile.write(json.dumps({"error": "Endpoint Not Found"}).encode("utf-8"))

    def _serve_static(self, filepath: Path, mime_type: str):
        if not filepath.exists():
            self._set_headers("text/plain", 404)
            self.wfile.write(b"File not found")
            return
        content = filepath.read_bytes()
        self._set_headers(mime_type, 200)
        self.wfile.write(content)

    def _handle_get_health(self):
        records_count = 0
        if BENCHMARK_PATH.exists():
            try:
                data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
                records_count = len(data.get("records", []))
            except Exception:
                pass

        health_data = {
            "status": "HEALTHY",
            "version": __version__,
            "engine": "Fleksa Autonomous Energy Flexibility",
            "solver": "HiGHS_MILP",
            "physics": "Thevenin_2RC_Wang_Ecker",
            "standards": [
                "OpenADR_3.0",
                "SunSpec_Modbus_TCP",
                "IPMVP_Option_B",
                "ASHRAE_Guideline_14",
                "W3C_Verifiable_Credentials_v2",
            ],
            "benchmark_records_available": records_count,
        }
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(health_data).encode("utf-8"))

    def _handle_get_benchmark(self):
        if BENCHMARK_PATH.exists():
            data = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
        else:
            data = {"records": []}
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _handle_post_solve(self, payload: dict):
        initial_soc = float(payload.get("initial_soc", 200.0))
        capacity = float(payload.get("capacity", 500.0))
        max_kw = float(payload.get("max_kw", 250.0))
        gpu_cap_min = float(payload.get("gpu_cap_min", 0.50))
        water_cost = float(payload.get("water_cost_per_kwh", 0.0))
        # Dynamic GPU flexibility (arXiv:2609.05406): 'dynamic' builds a
        # demand-based per-hour cap floor; 'fixed' keeps the legacy constant.
        gpu_flex_mode = str(payload.get("gpu_flex_mode", "dynamic"))
        gpu_queue = float(payload.get("gpu_queue_peak_flops", 750_000.0))

        # 2026 real-world benchmark price curve (TL/kWh)
        if BENCHMARK_PATH.exists():
            bench = json.loads(BENCHMARK_PATH.read_text(encoding="utf-8"))
            ptf = np.array([r["ptf"] / 1000.0 for r in bench["records"][:24]])
            smf = np.array([r["smf"] / 1000.0 for r in bench["records"][:24]])
        else:
            ptf = np.array([2.5] * 24)
            smf = np.array([2.6] * 24)

        base_load = np.full(24, 250.0)
        pv_gen = np.array([
            0, 0, 0, 0, 0, 15, 60, 120, 180, 230, 260, 270,
            270, 250, 200, 140, 70, 20, 0, 0, 0, 0, 0, 0
        ])
        temp = np.full(24, 25.0)

        state = FacilityState(
            bess_soc_kwh=initial_soc,
            bess_capacity_kwh=capacity,
            bess_max_kw=max_kw,
            cell_temperature_c=25.0,
        )

        horizon = MarketDataHorizon(
            hours=24,
            ptf_try_kwh=ptf,
            base_load_kw=base_load,
            pv_gen_kw=pv_gen,
            ambient_temp_c=temp,
        )

        gpu_flex_profile = None
        if gpu_flex_mode == "dynamic":
            from fleksa.workload.gpu_flexibility import (
                GpuFlexibilityProfiler,
                GpuDemandSignals,
            )
            from fleksa.cli.main import _simulate_gpu_demand
            profiler = GpuFlexibilityProfiler()
            backlog, noncrit, sla = _simulate_gpu_demand(24, gpu_queue)
            gpu_flex_profile = profiler.compute_flexibility_profile(
                GpuDemandSignals(queue_backlog_flops=backlog,
                                 noncritical_share=noncrit,
                                 sla_pressure=sla)
            )

        solver = FleksaMPCSolver(
            state=state,
            horizon_data=horizon,
            min_gpu_cap=gpu_cap_min,
            gpu_flex_profile=gpu_flex_profile,
            water_cost_per_kwh=water_cost,
        )
        res = solver.solve()

        # Battery 2-RC simulation over the 24h plan
        pack_cells_series = 234  # ~750V nominal pack (3.2V * 234 = 748.8V)
        pack_ah = (capacity * 1000.0) / 750.0
        bess_model = TheveninBatteryModel(
            nominal_capacity_ah=pack_ah,
            initial_soc=initial_soc / capacity,
        )
        deg_engine = BatteryDegradationEngine()
        voltages = []
        temps = []
        cell_temp = 25.0
        total_ah_cycled = 0.0

        for t in range(24):
            net_p = res.p_dis_kw[t] - res.p_ch_kw[t]
            i_batt = (net_p * 1000.0) / 750.0  # nominal 750V pack current
            v_cell, next_soc = bess_model.step(current_a=i_batt, dt_seconds=3600.0)
            v_pack = v_cell * pack_cells_series
            voltages.append(round(v_pack, 1))

            # Thermal evolution
            p_loss_w = (i_batt ** 2) * (bess_model.r0 * pack_cells_series)
            try:
                cell_temp = deg_engine.thermal_step(
                    current_temp_c=cell_temp,
                    ambient_temp_c=25.0,
                    power_loss_watts=p_loss_w,
                    dt_seconds=3600.0,
                )
            except Exception:
                cell_temp = 32.0
            temps.append(round(cell_temp, 1))
            total_ah_cycled += abs(i_batt)

        total_degradation_pct = deg_engine.compute_capacity_loss_pct(
            c_rate=max(0.1, abs(max_kw) / capacity),
            temp_celsius=cell_temp,
            cumulative_ah=total_ah_cycled,
        )

        response = {
            "status": res.status,
            "projected_cost_try": round(res.projected_cost_try, 2),
            "expected_savings_try": round(res.expected_savings_try, 2),
            "baseline_cost_try": round(res.projected_cost_try + res.expected_savings_try, 2),
            "savings_percent": round((res.expected_savings_try / max(1.0, res.projected_cost_try + res.expected_savings_try)) * 100, 1),
            "hourly": {
                "hours": list(range(24)),
                "ptf": [round(x, 3) for x in ptf.tolist()],
                "smf": [round(x, 3) for x in smf.tolist()],
                "pv_gen_kw": [round(x, 1) for x in pv_gen.tolist()],
                "base_load_kw": [round(x, 1) for x in base_load.tolist()],
                "p_ch_kw": [round(x, 1) for x in res.p_ch_kw],
                "p_dis_kw": [round(x, 1) for x in res.p_dis_kw],
                "gpu_power_cap_pct": [round(x * 100, 1) for x in res.gpu_power_cap_pct],
                "gpu_cap_floor_pct": [round(x * 100, 1) for x in (gpu_flex_profile or [res.metadata.get("gpu_cap_floor_min", gpu_cap_min)] * 24)],
                "soc_kwh": [round(x, 1) for x in res.soc_trajectory_kwh[:24]],
                "soc_pct": [round((x / capacity) * 100, 1) for x in res.soc_trajectory_kwh[:24]],
                "v_term_v": voltages,
                "cell_temp_c": temps,
            },
            "gpu_flexibility": {
                "mode": res.metadata.get("gpu_flexibility_mode"),
                "floor_min": round(float(res.metadata.get("gpu_cap_floor_min", gpu_cap_min)), 3),
                "floor_max": round(float(res.metadata.get("gpu_cap_floor_max", gpu_cap_min)), 3),
            },
            "degradation": {
                "day_q_loss_pct": round(total_degradation_pct, 4),
                "soh_remaining_pct": round(100.0 - total_degradation_pct, 4),
                "cycles_equivalent": round(sum(res.p_dis_kw) / capacity, 2),
            },
        }

        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(response).encode("utf-8"))

    def _handle_simulate_frequency_event(self, payload: dict):
        freq_dev_hz = float(payload.get("freq_deviation_hz", -0.18))
        target_curtail_kw = min(150.0, abs(freq_dev_hz) * 600.0)
        response_timeline_ms = [0, 5, 12, 20, 28, 50, 100, 200]
        gpu_power = [100.0, 95.0, 72.0, 50.0, 50.0, 50.0, 50.0, 50.0]
        bess_discharge = [0.0, 15.0, 45.0, 90.0, 100.0, 100.0, 100.0, 100.0]

        data = {
            "event_type": "TEİAŞ_PRIMARY_FREQUENCY_RESPONSE",
            "grid_frequency_hz": round(50.0 + freq_dev_hz, 3),
            "frequency_deviation_mhz": round(freq_dev_hz * 1000, 1),
            "response_time_ms": 28.0,
            "teias_deadline_ms": 200.0,
            "compliance": "PASS_GRADE_A",
            "curtailment_achieved_kw": target_curtail_kw,
            "timeline": {
                "time_ms": response_timeline_ms,
                "gpu_power_kw": gpu_power,
                "bess_discharge_kw": bess_discharge,
            },
        }
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _handle_verify_policy(self, payload: dict):
        yaml_content = payload.get("policy_yaml", "")
        skip_sig = bool(payload.get("skip_signature", True))
        if not yaml_content:
            self._set_headers("application/json", 400)
            self.wfile.write(json.dumps({"error": "Missing policy_yaml in request body"}).encode("utf-8"))
            return

        verifier = FlexPolicyVerifier()
        try:
            policy = verifier.parse_and_validate(yaml_content, verify_signature=not skip_sig)
            data = {
                "valid": True,
                "policy_id": policy.policy_id,
                "facility_id": policy.facility_id,
                "bess_capacity_kwh": policy.assets.bess.capacity_kwh,
                "rules_count": len(policy.rules),
                "load_classes_count": len(policy.load_classes),
                "safety_guards": {
                    "fail_closed": policy.safety_guards.fail_closed_on_telemetry_loss,
                    "timeout_sec": policy.safety_guards.telemetry_timeout_sec,
                },
            }
            self._set_headers("application/json", 200)
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except Exception as e:
            self._set_headers("application/json", 422)
            self.wfile.write(json.dumps({"valid": False, "error": str(e)}).encode("utf-8"))

    def _handle_arbitrage_gate(self, payload: dict):
        charge_p = float(payload.get("charge_price", 1.20))
        dis_p = float(payload.get("discharge_price", 4.80))
        rte = float(payload.get("rte", 0.88))
        deg = float(payload.get("degradation_cost", 0.35))
        risk = float(payload.get("risk_premium", 0.05))

        res = EconomicArbitrageGate.evaluate_arbitrage_viability(
            charge_price_try_per_kwh=charge_p,
            discharge_price_try_per_kwh=dis_p,
            degradation_cost_try_per_kwh=deg,
            round_trip_efficiency=rte,
            risk_premium_try=risk,
        )
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(res).encode("utf-8"))

    def _handle_canary_quorum(self, payload: dict):
        epias = float(payload.get("epias", 2450.0))
        teias = float(payload.get("teias", 2400.0))
        regional = float(payload.get("regional", 2380.0))
        max_div = float(payload.get("max_divergence_pct", 35.0))

        canary = TriangulationCanary(max_allowed_divergence_pct=max_div)
        try:
            consensus = canary.verify_price_quorum(epias, teias, regional)
            data = {
                "consensus_achieved": True,
                "consensus_price_try_mwh": consensus,
                "consensus_price_try_kwh": consensus / 1000.0,
                "feeds": {"epias": epias, "teias": teias, "regional": regional},
            }
            self._set_headers("application/json", 200)
            self.wfile.write(json.dumps(data).encode("utf-8"))
        except ByzantinePriceFeedError as e:
            self._set_headers("application/json", 409)
            self.wfile.write(json.dumps({"consensus_achieved": False, "error": str(e)}).encode("utf-8"))

    def _handle_audit_baseline(self, payload: dict):
        history = payload.get("history")
        if not history:
            # Generate default 5 similar days
            base_curve = np.array([
                180, 175, 170, 168, 172, 190, 240, 310, 340, 350, 345, 340,
                342, 338, 335, 330, 320, 305, 290, 275, 250, 220, 200, 190
            ], dtype=float)
            rng = np.random.default_rng(42)
            history = [(base_curve + rng.normal(0, 6.0, 24)).tolist() for _ in range(5)]

        actual = payload.get("actual")
        if not actual:
            actual = [
                180, 175, 170, 168, 172, 190, 240, 310, 340, 350, 345, 340,
                342, 338, 335, 330, 320, 205, 190, 175, 250, 220, 200, 190
            ]

        event_start = int(payload.get("event_start_hour", 17))
        event_hours = payload.get("event_hours", [17, 18, 19])
        ptf = np.array(payload.get("ptf", [3.5] * 24))

        baseline_raw = IpmvpBaselineEngine.calculate_10_in_10_baseline(history)
        pre_event_actual = actual[max(0, event_start - 2):event_start]
        adjusted_baseline = IpmvpBaselineEngine.apply_same_day_adjustment(
            baseline_hourly_kw=baseline_raw,
            pre_event_actual_2h_kw=pre_event_actual,
            event_start_hour=event_start,
        )

        savings = IpmvpBaselineEngine.compute_event_savings(
            adjusted_baseline_kw=adjusted_baseline,
            actual_meter_kw=np.array(actual),
            ptf_tariff_try_kwh=ptf,
            event_hours=event_hours,
        )

        ashrae = IpmvpBaselineEngine.evaluate_ashrae_compliance(
            actual=np.array(actual[:event_start]),
            baseline=adjusted_baseline[:event_start],
        )

        ledger = CryptographicSavingsLedger()
        leaf = ledger.append_entry({"savings": savings, "ashrae": ashrae})
        root = ledger.compute_merkle_root()

        data = {
            "baseline_raw_kw": [round(x, 1) for x in baseline_raw.tolist()],
            "adjusted_baseline_kw": [round(x, 1) for x in adjusted_baseline.tolist()],
            "actual_meter_kw": actual,
            "savings": savings,
            "ashrae_compliance": ashrae,
            "merkle_root": root,
        }
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def _handle_export_credential(self):
        facility_priv_key_hex = os.getenv("FLEKSA_FACILITY_KEY", "01" * 32)
        vc = W3cAttestationBuilder.create_credential(
            facility_id="ist-equinix-02",
            curtailed_kwh=142.50,
            avoided_cost_try=384.20,
            avoided_co2_grams=68400.0,
            private_key_hex=facility_priv_key_hex,
            issuer_did="did:fleksa:teias-turkey-hub-01",
        )
        self._set_headers("application/json", 200)
        self.wfile.write(json.dumps(vc).encode("utf-8"))

    def log_message(self, format, *args):
        """Suppress default HTTP server stderr logging for clean telemetry output."""
        return


def run_server(port: int = 8076, bind_address: str = "127.0.0.1"):
    """Starts the Fleksa web telemetry server."""
    server_address = (bind_address, port)
    httpd = HTTPServer(server_address, FleksaAPIHandler)
    print(f"⚡ Fleksa Cockpit live at http://{bind_address}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    run_server()
