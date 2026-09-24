"""
W3C Verifiable Credential v2.0 Builder and Verifier for Green Compute & Energy Flexibility.
"""

import json
from typing import Dict, Any
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class W3cAttestationBuilder:
    """
    Builds and verifies W3C Verifiable Credentials for certified energy curtailment events.
    """

    @classmethod
    def create_credential(
        cls,
        facility_id: str,
        curtailed_kwh: float,
        avoided_cost_try: float,
        avoided_co2_grams: float,
        private_key_hex: str,
        issuer_did: str = "did:fleksa:authority:mainnet",
    ) -> Dict[str, Any]:
        now_str = datetime.now(timezone.utc).isoformat()
        cred_id = f"urn:fleksa:attestation:{int(datetime.now(timezone.utc).timestamp())}"

        credential_body = {
            "@context": [
                "https://www.w3.org/ns/credentials/v2",
                "https://w3id.org/security/suites/ed25519-2020/v1",
                "https://schema.fleksa.energy/v1"
            ],
            "id": cred_id,
            "type": ["VerifiableCredential", "GreenComputeFlexibilityCredential"],
            "issuer": issuer_did,
            "validFrom": now_str,
            "credentialSubject": {
                "id": f"did:kredent:facility:{facility_id}",
                "curtailedEnergyKwh": round(curtailed_kwh, 2),
                "avoidedGridCostTry": round(avoided_cost_try, 2),
                "avoidedCarbonEmissionsGramsCO2e": round(avoided_co2_grams, 2),
            },
        }

        # Canonicalize and sign
        canonical_bytes = json.dumps(credential_body, sort_keys=True, separators=(',', ':')).encode("utf-8")
        priv_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
        sig_bytes = priv_key.sign(canonical_bytes)

        credential_body["proof"] = {
            "type": "Ed25519Signature2020",
            "created": now_str,
            "verificationMethod": f"{issuer_did}#key-1",
            "proofPurpose": "assertionMethod",
            "proofValue": sig_bytes.hex(),
        }

        return credential_body

    @classmethod
    def verify_credential(cls, credential_json: Dict[str, Any], public_key_hex: str) -> bool:
        proof = credential_json.get("proof")
        if not proof or proof.get("type") != "Ed25519Signature2020":
            return False

        sig_hex = proof.get("proofValue")
        if not sig_hex:
            return False

        clean_cred = dict(credential_json)
        clean_cred.pop("proof", None)
        canonical_bytes = json.dumps(clean_cred, sort_keys=True, separators=(',', ':')).encode("utf-8")

        try:
            pub_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(public_key_hex))
            pub_key.verify(bytes.fromhex(sig_hex), canonical_bytes)
            return True
        except Exception:
            return False
