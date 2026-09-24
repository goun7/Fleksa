"""
Pytest configuration and shared fixtures for Fleksa test suite.
"""

import pytest
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fleksa.core.types import FacilityState, MarketDataHorizon


@pytest.fixture
def sample_facility_state() -> FacilityState:
    return FacilityState(
        bess_soc_kwh=200.0,
        bess_capacity_kwh=500.0,
        bess_max_kw=250.0,
        min_soc_pct=0.15,
        max_soc_pct=0.95,
        eta_rt=0.88,
        indoor_temp_c=22.0,
        queue_backlog=10.0,
        cell_temperature_c=25.0,
        state_of_health=1.0,
    )


@pytest.fixture
def sample_horizon_data() -> MarketDataHorizon:
    hours = 24
    # Classic duck curve: low in afternoon (GES), peak in evening (18-21)
    ptf = np.array([
        2.2, 2.0, 1.8, 1.6, 1.7, 2.1, 2.8, 3.2, 2.5, 1.8, 1.2, 0.9,
        0.8, 0.9, 1.1, 1.6, 2.4, 3.8, 4.9, 5.2, 4.6, 3.5, 2.8, 2.4
    ])
    base_load = np.full(hours, 200.0)
    pv_gen = np.array([
        0, 0, 0, 0, 0, 10, 30, 80, 120, 160, 180, 200,
        200, 170, 130, 80, 30, 10, 0, 0, 0, 0, 0, 0
    ], dtype=float)
    ambient_temp = np.full(hours, 25.0)

    return MarketDataHorizon(
        hours=hours,
        ptf_try_kwh=ptf,
        base_load_kw=base_load,
        pv_gen_kw=pv_gen,
        ambient_temp_c=ambient_temp,
    )


@pytest.fixture
def ed25519_keypair():
    priv = Ed25519PrivateKey.generate()
    pub = priv.public_key()
    priv_hex = priv.private_bytes_raw().hex()
    pub_hex = pub.public_bytes_raw().hex()
    return {"private_hex": priv_hex, "public_hex": pub_hex}


@pytest.fixture(scope="session")
def live_server():
    import threading
    import time
    from fleksa.server.app import run_server
    port = 8097
    host = "127.0.0.1"
    server_thread = threading.Thread(
        target=run_server,
        kwargs={"port": port, "bind_address": host},
        daemon=True
    )
    server_thread.start()
    time.sleep(0.5)
    return f"http://{host}:{port}"

