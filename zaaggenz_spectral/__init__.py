"""Phase-coherent retuning, multi-comb shaping and explicit nonlinear placement experiments."""
from .model import (METHOD_ID,METHOD_VERSION,SpectralRetuneError,LatticeVoice,LatticeSegment,
                    SpectralRetuneRequest,TargetTooth,FrameDecision)
from .lattice import (cents_distance,cents_ratio,build_target_lattice,build_target_schedule,
                      lattice_at,nearest_tooth)
from .engine import SpectralRetunePlan,SpectralRetuneResult,retune_components,inspection_payload
from .jobs import estimate_retune_memory_bytes,make_retune_executor,submit_retune_job
from .chordness_model import ChordnessError,CombTemplate,ChordnessCoefficients
from .chordness_request import ChordnessRequest
from .chordness_templates import harmonic_comb,templates_from_voicing_frame
from .chordness_descriptors import evaluate_template,evaluate_union,select_templates,objective_terms
from .chordness_result import ChordnessFrameDecision,ChordnessResult
from .chordness_engine import apply_chordness,chordness_inspection
from .chordness_jobs import estimate_chordness_memory_bytes,make_chordness_executor,submit_chordness_job
from .placement import (PlacementError,NonlinearStageSpec,PlacementRequest,PlacementResult,
                        run_placement,run_family,PLACEMENTS)

__all__=['METHOD_ID','METHOD_VERSION','SpectralRetuneError','LatticeVoice','LatticeSegment',
         'SpectralRetuneRequest','TargetTooth','FrameDecision','cents_distance','cents_ratio',
         'build_target_lattice','build_target_schedule','lattice_at','nearest_tooth',
         'SpectralRetunePlan','SpectralRetuneResult','retune_components','inspection_payload',
         'estimate_retune_memory_bytes','make_retune_executor','submit_retune_job',
         'ChordnessError','CombTemplate','ChordnessCoefficients','ChordnessRequest','harmonic_comb',
         'templates_from_voicing_frame','evaluate_template','evaluate_union','select_templates','objective_terms',
         'ChordnessFrameDecision','ChordnessResult','apply_chordness','chordness_inspection',
         'estimate_chordness_memory_bytes','make_chordness_executor','submit_chordness_job',
         'PlacementError','NonlinearStageSpec','PlacementRequest','PlacementResult','run_placement','run_family','PLACEMENTS']
