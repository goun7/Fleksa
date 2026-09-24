"""
Exception hierarchy for Fleksa.
"""

class FleksaError(Exception):
    """Base exception for all Fleksa engine errors."""


class PolicyVerificationError(FleksaError):
    """Raised when a Flex-Policy fails cryptographic signature or schema validation."""


class SafetyGuardViolationError(FleksaError):
    """Raised when a policy or optimization action violates a physical or regulatory safety guard."""


class InvariantViolationError(FleksaError):
    """Raised when a core invariant (e.g. transformer thermal limit or SoC boundary) is breached."""


class OptimizationConvergenceError(FleksaError):
    """Raised when the MILP/MPC solver fails to find a feasible or optimal dispatch schedule."""


class ByzantinePriceFeedError(FleksaError):
    """Raised when Triangulation Canary rejects corrupted or conflicting market price feeds."""

