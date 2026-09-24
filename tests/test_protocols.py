"""
Unit tests for OpenADR 3.0 VEN, SunSpec Modbus, and W3C Attestation.
"""

import pytest
from fleksa.protocols.openadr import OpenAdrVenHandler
from fleksa.protocols.modbus import SunSpecInverterMapper
from fleksa.protocols.attestation import W3cAttestationBuilder


def test_openadr_ven_opt_in():
    ven = OpenAdrVenHandler(ven_id="ven-ankara-01", facility_max_curtail_kw=200.0)
    event_payload = {"event_id": "evt-grid-991", "target_curtail_kw": 150.0, "duration_seconds": 3600}

    # Adequate SoC (60%) -> Should Opt-In
    resp = ven.handle_event(event_payload, current_soc_pct=60.0)
    assert resp["opt_type"] == "OPT_IN"
    assert resp["committed_curtail_kw"] == 150.0


def test_openadr_ven_opt_out_on_low_battery():
    ven = OpenAdrVenHandler(ven_id="ven-ankara-01", facility_max_curtail_kw=200.0)
    event_payload = {"event_id": "evt-grid-992", "target_curtail_kw": 180.0, "duration_seconds": 3600}

    # Low SoC (12%) -> Must Opt-Out to protect facility continuity
    resp = ven.handle_event(event_payload, current_soc_pct=12.0)
    assert resp["opt_type"] == "OPT_OUT"
    assert resp["reason"] == "INSUFFICIENT_BESS_RESERVE_SOC"


def test_sunspec_modbus_roundtrip():
    # Encode charge command
    regs = SunSpecInverterMapper.encode_command(
        active_power_limit_pct=85.0,
        mode="CHARGE",
        setpoint_kw=-150.0,
        min_reserve_pct=20.0,
    )

    decoded = SunSpecInverterMapper.decode_registers(regs)
    assert decoded["active_power_limit_pct"] == 85.0
    assert decoded["storage_mode"] == "CHARGE"
    assert decoded["setpoint_kw"] == -150.0
    assert decoded["min_reserve_pct"] == 20.0

    # Test AUTO and DISABLED modes
    auto_regs = SunSpecInverterMapper.encode_command(100.0, "AUTO", 0.0)
    assert SunSpecInverterMapper.decode_registers(auto_regs)["storage_mode"] == "AUTO"

    dis_regs = SunSpecInverterMapper.encode_command(0.0, "DISABLED", 0.0)
    assert SunSpecInverterMapper.decode_registers(dis_regs)["storage_mode"] == "DISABLED"



def test_w3c_attestation_lifecycle(ed25519_keypair):
    cred = W3cAttestationBuilder.create_credential(
        facility_id="dc-ankara-01",
        curtailed_kwh=412.5,
        avoided_cost_try=1980.0,
        avoided_co2_grams=185625.0,
        private_key_hex=ed25519_keypair["private_hex"],
    )

    assert cred["type"] == ["VerifiableCredential", "GreenComputeFlexibilityCredential"]
    assert cred["credentialSubject"]["curtailedEnergyKwh"] == 412.50

    # Verify signature
    valid = W3cAttestationBuilder.verify_credential(cred, ed25519_keypair["public_hex"])
    assert valid is True

    # Tampering check
    tampered = dict(cred)
    tampered["credentialSubject"] = dict(cred["credentialSubject"])
    tampered["credentialSubject"]["curtailedEnergyKwh"] = 999.99
    assert W3cAttestationBuilder.verify_credential(tampered, ed25519_keypair["public_hex"]) is False


def test_modbus_tcp_binary_frame_roundtrip():
    regs = {
        40083: 8500,
        40084: 1,
        40085: 500,
        40086: 2000,
    }

    frame = SunSpecInverterMapper.build_modbus_tcp_write_frame(
        registers=regs,
        unit_id=1,
        transaction_id=42
    )

    # Frame should start with Transaction ID 42 (0x002A) and Protocol ID 0 (0x0000)
    assert frame[:2] == b"\x00\x2a"
    assert frame[2:4] == b"\x00\x00"

    # Simulated valid slave response: Transaction ID 42, Proto 0, Len 6, Unit 1, FC 0x10, Start 82, Qty 4
    import struct
    simulated_raw_frame = struct.pack(">HHHBBHH", 42, 0, 6, 1, 0x10, 82, 4)
    parsed = SunSpecInverterMapper.parse_modbus_tcp_response(simulated_raw_frame)

    assert parsed["transaction_id"] == 42
    assert parsed["unit_id"] == 1
    assert parsed["function_code"] == 16
    assert parsed["starting_address"] == 40083
    assert parsed["quantity"] == 4
