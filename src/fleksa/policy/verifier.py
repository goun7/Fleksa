"""
Cryptographic Ed25519 signature validator and AST safety guard verifier for Flex-Policy v2.
"""

import json
from typing import Dict, Any, Optional, List
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from fleksa.policy.schema import FlexPolicyEnvelope, FlexPolicyDocument
from fleksa.core.errors import PolicyVerificationError, SafetyGuardViolationError


class FlexPolicyVerifier:
    """
    Parses, validates, cryptographically verifies, and evaluates Flex-Policy v2 specifications.
    """

    def __init__(self, trusted_public_keys: Optional[Dict[str, str]] = None):
        """
        trusted_public_keys: Dict mapping key_id -> 32-byte hex public key
        """
        self.trusted_keys = trusted_public_keys or {}

    def parse_and_validate(self, yaml_content: str, verify_signature: bool = True) -> FlexPolicyDocument:
        try:
            raw_dict = yaml.safe_load(yaml_content)
        except Exception as e:
            raise PolicyVerificationError(f"YAML parsing error: {e}") from e

        try:
            envelope = FlexPolicyEnvelope.model_validate(raw_dict)
        except Exception as e:
            raise PolicyVerificationError(f"Flex-Policy schema validation error: {e}") from e

        policy = envelope.flex_policy

        # Safety Guard invariant checks
        if not policy.safety_guards.fail_closed_on_telemetry_loss:
            raise SafetyGuardViolationError("Policy invariant violation: fail_closed_on_telemetry_loss MUST be true.")

        if policy.assets.bess.min_soc_pct < 10.0:
            raise SafetyGuardViolationError("Policy invariant violation: min_soc_pct cannot be below 10.0%.")

        if policy.assets.bess.max_soc_pct > 98.0:
            raise SafetyGuardViolationError("Policy invariant violation: max_soc_pct cannot exceed 98.0%.")

        # Cryptographic Signature Verification
        if verify_signature:
            self._verify_signature(raw_dict.get("flex_policy", {}))

        return policy

    def _verify_signature(self, policy_dict: Dict[str, Any]) -> None:
        crypto = policy_dict.get("crypto_signature")
        if not crypto:
            raise PolicyVerificationError("Missing required crypto_signature block in policy.")

        key_id = crypto.get("key_id")
        sig_hex = crypto.get("sig")

        if not key_id or not sig_hex:
            raise PolicyVerificationError("crypto_signature requires valid key_id and sig fields.")

        pub_key_hex = self.trusted_keys.get(key_id)
        if not pub_key_hex:
            raise PolicyVerificationError(f"Unknown or untrusted Ed25519 key_id: {key_id}")

        # Deterministic canonical serialization: remove signature block
        clean_policy = dict(policy_dict)
        clean_policy.pop("crypto_signature", None)
        canonical_bytes = json.dumps(clean_policy, sort_keys=True, separators=(',', ':')).encode("utf-8")

        try:
            pub_bytes = bytes.fromhex(pub_key_hex)
            sig_bytes = bytes.fromhex(sig_hex)
            public_key = Ed25519PublicKey.from_public_bytes(pub_bytes)
            public_key.verify(sig_bytes, canonical_bytes)
        except Exception as e:
            raise PolicyVerificationError(f"Ed25519 cryptographic signature verification failed: {e}") from e

    @staticmethod
    def evaluate_rules(policy: FlexPolicyDocument, telemetry: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        Evaluates policy rules against live telemetry.
        Returns list of actions to trigger.
        """
        triggered_actions = []

        for rule in policy.rules:
            cond = rule.condition
            # Support simple 'and' logic
            all_match = True
            and_clauses = cond.get("and", [cond])

            for clause in and_clauses:
                for metric_key, constraints in clause.items():
                    current_val = telemetry.get(metric_key)
                    if current_val is None:
                        all_match = False
                        break

                    if isinstance(constraints, dict):
                        if "gt" in constraints and not (current_val > constraints["gt"]):
                            all_match = False
                        if "lt" in constraints and not (current_val < constraints["lt"]):
                            all_match = False
                        if "gte" in constraints and not (current_val >= constraints["gte"]):
                            all_match = False
                        if "lte" in constraints and not (current_val <= constraints["lte"]):
                            all_match = False

            if all_match:
                for action in rule.actions:
                    triggered_actions.append({
                        "rule_id": rule.id,
                        "target": action.target,
                        "command": action.command,
                        "power_kw": action.power_kw,
                        "value_pct": action.value_pct,
                        "audit_note": rule.audit_note,
                    })

        return triggered_actions
