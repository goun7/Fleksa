"""
Pydantic v2 schemas for Flex-Policy v2 specification.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class CryptoSignature(BaseModel):
    key_id: str
    algorithm: str = "Ed25519"
    sig: str


class BessAssetConfig(BaseModel):
    capacity_kwh: float = Field(gt=0.0)
    max_charge_kw: float = Field(gt=0.0)
    max_discharge_kw: float = Field(gt=0.0)
    min_soc_pct: float = Field(ge=5.0, le=30.0, default=15.0)
    max_soc_pct: float = Field(ge=80.0, le=100.0, default=95.0)
    max_daily_cycles: float = Field(ge=0.5, le=3.0, default=1.5)
    chemistry: str = "LFP"


class ComputeAssetConfig(BaseModel):
    max_power_kw: float = Field(gt=0.0)
    min_critical_kw: float = Field(ge=0.0)
    gpu_nodes_count: int = Field(ge=0, default=0)
    allow_dvfs_capping: bool = True


class AssetsConfig(BaseModel):
    bess: BessAssetConfig
    compute: ComputeAssetConfig


class LoadClassDefinition(BaseModel):
    id: str
    priority: int
    interruptible: bool
    max_delay_hours: Optional[int] = None
    checkpoint_notice_sec: Optional[int] = None
    allow_power_cap_pct: Optional[float] = None


class RuleAction(BaseModel):
    target: str
    command: str
    power_kw: Optional[float] = None
    value_pct: Optional[float] = None


class RuleDefinition(BaseModel):
    id: str
    condition: Dict[str, Any]
    actions: List[RuleAction]
    audit_note: Optional[str] = None


class SafetyGuardsConfig(BaseModel):
    fail_closed_on_telemetry_loss: bool = True
    telemetry_timeout_sec: float = Field(ge=10.0, le=300.0, default=90.0)
    max_grid_export_limit_kw: float = 0.0
    human_in_the_loop_triggers: List[str] = Field(default_factory=list)


class FlexPolicyDocument(BaseModel):
    version: str = "2.0.0"
    policy_id: str
    facility_id: str
    created_at: str
    valid_until: str
    crypto_signature: Optional[CryptoSignature] = None
    assets: AssetsConfig
    load_classes: List[LoadClassDefinition]
    rules: List[RuleDefinition]
    safety_guards: SafetyGuardsConfig


class FlexPolicyEnvelope(BaseModel):
    flex_policy: FlexPolicyDocument
