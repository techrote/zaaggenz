"""Exact metrical hierarchy, cross-clock and periodicity-overlay authoring."""
from .model import (MeterError, MeterPlan, VERSION, KINDS, CONTROLS, LAYERS,
                    MAX_TICKS_PER_CLOCK, MAX_TOTAL_TICKS, MAX_CONTROL_ROWS,
                    work_estimate)
from .engine import clock_relation, generate_ticks, generate_all_ticks, control_schedule
from .overlay import periodicity_overlay, feature_flux_samples, overlay_feature_flux
from .presets import nested_124_cross32

__all__ = ['MeterError', 'MeterPlan', 'VERSION', 'KINDS', 'CONTROLS', 'LAYERS',
           'MAX_TICKS_PER_CLOCK', 'MAX_TOTAL_TICKS', 'MAX_CONTROL_ROWS', 'work_estimate',
           'clock_relation', 'generate_ticks', 'generate_all_ticks', 'control_schedule',
           'periodicity_overlay', 'feature_flux_samples', 'overlay_feature_flux',
           'nested_124_cross32']
