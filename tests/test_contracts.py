"""
Tests for Fleksa Solidity Smart Contract specification and integrity.
"""

from pathlib import Path
import re


def test_solidity_contract_integrity():
    contract_path = Path(__file__).parent.parent / "contracts" / "FleksaEnergyLedger.sol"
    assert contract_path.exists(), "Contract file must exist"

    content = contract_path.read_text(encoding="utf-8")

    # Verify SPDX license & pragma
    assert "SPDX-License-Identifier: MIT" in content
    assert "pragma solidity ^0.8.24;" in content

    # Verify Core Struct
    assert "struct FlexibilityRecord" in content
    assert "bytes32 merkleRoot;" in content
    assert "uint64 timestamp;" in content
    assert "uint32 curtailedKwh;" in content
    assert "uint32 avoidedCo2Grams;" in content
    assert "uint32 settlementAmountTry;" in content
    assert "bool verified;" in content

    # Verify Events
    assert "event FlexibilityAttested" in content
    assert "event RecordAudited" in content
    assert "event AuditorUpdated" in content

    # Verify Core Functions
    assert "function attestFlexibility" in content
    assert "function verifyRecord" in content
    assert "function getRecordCount" in content
    assert "function getRecord" in content
    assert "function setAuditor" in content
    assert "function setPaused" in content

    # Check balanced braces
    open_braces = content.count("{")
    close_braces = content.count("}")
    assert open_braces == close_braces, f"Mismatched braces: {open_braces} vs {close_braces}"
