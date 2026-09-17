"""ZG-024d preregistered staged deterministic inverse-search research.

This package is intentionally outside :mod:`zaaggenz_inverse`: ZG-024a/b and their
frozen implementation/calibration identities remain reproducible.  Production search
is not changed unless the frozen confirmation rule in this pass independently earns
that decision.
"""

from .staged import (
    StageDefinition,
    StagedPlan,
    StagedCheckpoint,
    StagedInterrupted,
    StagedResumeDivergence,
    StagedResult,
    run_staged,
)

__all__ = [
    "StageDefinition",
    "StagedPlan",
    "StagedCheckpoint",
    "StagedInterrupted",
    "StagedResumeDivergence",
    "StagedResult",
    "run_staged",
]
