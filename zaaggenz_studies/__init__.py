"""Versioned preregistration, study-evidence and reproducible statistics for ZG-040."""

from .model import (
    VERSION, FAMILIES, MODES, SCALES, METHODS, StudyError, StudyManifest,
    FrozenStudy, StudyAmendment, StudyDeviation,
    verify_frozen_manifest, changed_paths, make_amendment,
    verify_amendment_chain, make_deviation,
)
from .corrective import (
    StudyDataset, StudyEvidencePlan, freeze_evidence_plan,
    freeze_manifest, SimulationAssumptions, balanced_cyclic_orders,
    simulate_crossed_design, plan_precision,
)
from .public import analyse_study

__all__ = [
    "VERSION", "FAMILIES", "MODES", "SCALES", "METHODS", "StudyError",
    "StudyManifest", "FrozenStudy", "StudyAmendment", "StudyDeviation",
    "freeze_manifest", "verify_frozen_manifest", "changed_paths",
    "make_amendment", "verify_amendment_chain", "make_deviation",
    "StudyDataset", "StudyEvidencePlan", "freeze_evidence_plan",
    "analyse_study", "SimulationAssumptions", "balanced_cyclic_orders",
    "simulate_crossed_design", "plan_precision",
]
