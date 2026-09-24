// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/**
 * @title FleksaEnergyLedger
 * @notice Cryptographic settlement ledger for Demand Response (DR), BESS flexibility,
 *         and certified carbon abatement verifiable credentials.
 * @dev Compliant with W3C Verifiable Credentials v2.0 & EAS (Ethereum Attestation Service) schema.
 */
contract FleksaEnergyLedger {
    struct FlexibilityRecord {
        bytes32 merkleRoot;        // SHA-256 Merkle root of the 24-hour interval
        uint64 timestamp;          // Unix timestamp of interval settlement
        uint32 curtailedKwh;       // Curtailed or shifted energy in kWh (scaled x100)
        uint32 avoidedCo2Grams;    // Avoided CO2 in grams (scaled x100)
        uint32 settlementAmountTry;// Financial settlement yield in TRY (scaled x100)
        bool verified;             // True if verified by designated grid auditor / TSO
    }

    address public owner;
    address public gridAuditor;
    bool public paused;

    // Facility DID hash => Record Array
    mapping(bytes32 => FlexibilityRecord[]) private _facilityRecords;

    // Event emitted upon successful flexibility attestation
    event FlexibilityAttested(
        bytes32 indexed facilityIdHash,
        bytes32 indexed merkleRoot,
        uint64 timestamp,
        uint32 curtailedKwh,
        uint32 settlementAmountTry
    );

    event RecordAudited(bytes32 indexed facilityIdHash, uint256 recordIndex, bool verified);
    event AuditorUpdated(address indexed previousAuditor, address indexed newAuditor);

    modifier onlyOwner() {
        require(msg.sender == owner, "Fleksa: Caller is not owner");
        _;
    }

    modifier onlyAuditor() {
        require(msg.sender == gridAuditor || msg.sender == owner, "Fleksa: Caller is not auditor");
        _;
    }

    modifier whenNotPaused() {
        require(!paused, "Fleksa: Contract is paused");
        _;
    }

    constructor(address _gridAuditor) {
        require(_gridAuditor != address(0), "Fleksa: Invalid auditor address");
        owner = msg.sender;
        gridAuditor = _gridAuditor;
    }

    function attestFlexibility(
        bytes32 facilityIdHash,
        bytes32 merkleRoot,
        uint32 curtailedKwh,
        uint32 avoidedCo2Grams,
        uint32 settlementAmountTry
    ) external whenNotPaused returns (uint256 recordIndex) {
        require(facilityIdHash != bytes32(0), "Fleksa: Invalid facility ID");
        require(merkleRoot != bytes32(0), "Fleksa: Invalid Merkle root");

        FlexibilityRecord memory newRecord = FlexibilityRecord({
            merkleRoot: merkleRoot,
            timestamp: uint64(block.timestamp),
            curtailedKwh: curtailedKwh,
            avoidedCo2Grams: avoidedCo2Grams,
            settlementAmountTry: settlementAmountTry,
            verified: (msg.sender == gridAuditor)
        });

        _facilityRecords[facilityIdHash].push(newRecord);
        recordIndex = _facilityRecords[facilityIdHash].length - 1;

        emit FlexibilityAttested(
            facilityIdHash,
            merkleRoot,
            uint64(block.timestamp),
            curtailedKwh,
            settlementAmountTry
        );
    }

    function verifyRecord(bytes32 facilityIdHash, uint256 recordIndex) external onlyAuditor {
        require(recordIndex < _facilityRecords[facilityIdHash].length, "Fleksa: Record out of bounds");
        _facilityRecords[facilityIdHash][recordIndex].verified = true;
        emit RecordAudited(facilityIdHash, recordIndex, true);
    }

    function getRecordCount(bytes32 facilityIdHash) external view returns (uint256) {
        return _facilityRecords[facilityIdHash].length;
    }

    function getRecord(bytes32 facilityIdHash, uint256 index)
        external
        view
        returns (
            bytes32 merkleRoot,
            uint64 timestamp,
            uint32 curtailedKwh,
            uint32 avoidedCo2Grams,
            uint32 settlementAmountTry,
            bool verified
        )
    {
        require(index < _facilityRecords[facilityIdHash].length, "Fleksa: Record out of bounds");
        FlexibilityRecord memory r = _facilityRecords[facilityIdHash][index];
        return (
            r.merkleRoot,
            r.timestamp,
            r.curtailedKwh,
            r.avoidedCo2Grams,
            r.settlementAmountTry,
            r.verified
        );
    }

    function setAuditor(address newAuditor) external onlyOwner {
        require(newAuditor != address(0), "Fleksa: Zero address");
        emit AuditorUpdated(gridAuditor, newAuditor);
        gridAuditor = newAuditor;
    }

    function setPaused(bool _paused) external onlyOwner {
        paused = _paused;
    }
}
