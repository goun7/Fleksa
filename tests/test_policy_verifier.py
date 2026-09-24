"""
Unit tests for Flex-Policy v2 Schema and Ed25519 Signature Verification.
"""

import json
import yaml
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from fleksa.policy.verifier import FlexPolicyVerifier
from fleksa.core.errors import PolicyVerificationError, SafetyGuardViolationError


def create_signed_policy_yaml(priv_hex: str, key_id: str = "key-test-01") -> str:
    policy_dict = {
        "flex_policy": {
            "version": "2.0.0",
            "policy_id": "pol-test-01",
            "facility_id": "fac-ankara-01",
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
                {"id": "class-0", "priority": 0, "interruptible": False},
                {"id": "class-1", "priority": 1, "interruptible": True},
            ],
            "rules": [
                {
                    "id": "rule-peak",
                    "condition": {"and": [{"price_ptf": {"gt": 4.0}}, {"bess_soc": {"gt": 20.0}}]},
                    "actions": [{"target": "bess", "command": "discharge", "power_kw": 200.0}],
                    "audit_note": "Discharge during super peak",
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

    # Sign canonical bytes
    canonical_bytes = json.dumps(policy_dict["flex_policy"], sort_keys=True, separators=(',', ':')).encode("utf-8")
    priv = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(priv_hex))
    sig = priv.sign(canonical_bytes).hex()

    policy_dict["flex_policy"]["crypto_signature"] = {
        "key_id": key_id,
        "algorithm": "Ed25519",
        "sig": sig,
    }

    return yaml.dump(policy_dict)


def test_valid_policy_signature(ed25519_keypair):
    yaml_text = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    verifier = FlexPolicyVerifier(trusted_public_keys={"key-test-01": ed25519_keypair["public_hex"]})

    policy = verifier.parse_and_validate(yaml_text, verify_signature=True)
    assert policy.policy_id == "pol-test-01"
    assert policy.assets.bess.capacity_kwh == 500.0


def test_tampered_policy_signature_rejected(ed25519_keypair):
    yaml_text = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    # Tamper with the policy by changing capacity
    tampered_text = yaml_text.replace("capacity_kwh: 500.0", "capacity_kwh: 800.0")

    verifier = FlexPolicyVerifier(trusted_public_keys={"key-test-01": ed25519_keypair["public_hex"]})
    with pytest.raises(PolicyVerificationError, match="Ed25519 cryptographic signature verification failed"):
        verifier.parse_and_validate(tampered_text, verify_signature=True)


def test_safety_guard_invariant_rejection(ed25519_keypair):
    yaml_text = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    # Tamper safety guard
    bad_guard_text = yaml_text.replace("fail_closed_on_telemetry_loss: true", "fail_closed_on_telemetry_loss: false")

    verifier = FlexPolicyVerifier(trusted_public_keys={"key-test-01": ed25519_keypair["public_hex"]})
    with pytest.raises(SafetyGuardViolationError, match="fail_closed_on_telemetry_loss MUST be true"):
        verifier.parse_and_validate(bad_guard_text, verify_signature=False)


def test_rule_evaluation(ed25519_keypair):
    yaml_text = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    verifier = FlexPolicyVerifier(trusted_public_keys={"key-test-01": ed25519_keypair["public_hex"]})
    policy = verifier.parse_and_validate(yaml_text, verify_signature=True)

    # Condition: price_ptf > 4.0 and bess_soc > 20.0
    actions_triggered = verifier.evaluate_rules(policy, {"price_ptf": 4.80, "bess_soc": 50.0})
    assert len(actions_triggered) == 1
    assert actions_triggered[0]["command"] == "discharge"
    assert actions_triggered[0]["power_kw"] == 200.0

    # Low price: rule should not trigger
    actions_none = verifier.evaluate_rules(policy, {"price_ptf": 2.50, "bess_soc": 50.0})
    assert len(actions_none) == 0


def test_policy_verifier_invalid_soc_limits(ed25519_keypair):
    yaml_text = create_signed_policy_yaml(ed25519_keypair["private_hex"])
    verifier = FlexPolicyVerifier()

    # min_soc below 10%
    low_soc = yaml_text.replace("min_soc_pct: 15.0", "min_soc_pct: 6.0")
    with pytest.raises(SafetyGuardViolationError, match="min_soc_pct cannot be below"):
        verifier.parse_and_validate(low_soc, verify_signature=False)

    # max_soc above 98%
    high_soc = yaml_text.replace("max_soc_pct: 95.0", "max_soc_pct: 99.0")
    with pytest.raises(SafetyGuardViolationError, match="max_soc_pct cannot exceed"):
        verifier.parse_and_validate(high_soc, verify_signature=False)


def test_policy_verifier_missing_signature_fields():
    verifier = FlexPolicyVerifier()
    invalid_yaml = "flex_policy:\n  version: '2.0.0'\n  policy_id: 'p'\n  facility_id: 'f'\n  created_at: '2026-09-16'\n  valid_until: '2026-12-31'\n  assets:\n    bess:\n      capacity_kwh: 500\n      max_charge_kw: 250\n      max_discharge_kw: 250\n    compute:\n      max_power_kw: 400\n      min_critical_kw: 100\n  load_classes: []\n  rules: []\n  safety_guards:\n    fail_closed_on_telemetry_loss: true\n"
    with pytest.raises(PolicyVerificationError, match="Missing required crypto_signature"):
        verifier.parse_and_validate(invalid_yaml, verify_signature=True)

