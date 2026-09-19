"""Versioned preregistration, study-evidence and reproducible statistics for ZG-040."""

from .model import (
    VERSION, FAMILIES, MODES, SCALES, METHODS, StudyError, StudyManifest,
    FrozenStudy, StudyAmendment, StudyDeviation, freeze_manifest,
    verify_frozen_manifest, changed_paths, make_amendment,
    verify_amendment_chain, make_deviation,
)
from .analysis import StudyDataset, analyse_study
from .design import (
    SimulationAssumptions, balanced_cyclic_orders, simulate_crossed_design,
    plan_precision,
)

__all__ = [
    "VERSION", "FAMILIES", "MODES", "SCALES", "METHODS", "StudyError",
    "StudyManifest", "FrozenStudy", "StudyAmendment", "StudyDeviation",
    "freeze_manifest", "verify_frozen_manifest", "changed_paths",
    "make_amendment", "verify_amendment_chain", "make_deviation",
    "StudyDataset", "analyse_study", "SimulationAssumptions",
    "balanced_cyclic_orders", "simulate_crossed_design", "plan_precision",
]
