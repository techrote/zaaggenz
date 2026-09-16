"""Phase-coherent retuning, multi-comb shaping, placement and band-selective DSP experiments."""
from .model import (METHOD_ID,METHOD_VERSION,SpectralRetuneError,LatticeVoice,LatticeSegment,
                    SpectralRetuneRequest,TargetTooth,FrameDecision,MAX_RETUNE_SEGMENTS,
                    MAX_RETUNE_CANDIDATE_TEETH,RETUNE_TARGET_TOOTH_RESERVATION_BYTES,
                    RETUNE_TARGET_SEGMENT_RESERVATION_BYTES,retune_request_work_counts,
                    estimate_retune_target_bytes)
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
from .placement_jobs import (estimate_placement_memory_bytes,make_placement_executor,submit_placement_job,
                             make_family_executor,submit_placement_family_job)
from .placement_metrics import (pcm_sha256,spectral_metrics,level_metrics,transient_metrics,
                                summarize_audio,difference_metrics)
from .band_selective import (BandSelectiveError,BandSlotSpec,BandSelectiveRequest,BandSelectiveResult,
                             process_band_selective)

__all__=['METHOD_ID','METHOD_VERSION','SpectralRetuneError','LatticeVoice','LatticeSegment',
         'SpectralRetuneRequest','TargetTooth','FrameDecision','MAX_RETUNE_SEGMENTS',
         'MAX_RETUNE_CANDIDATE_TEETH','RETUNE_TARGET_TOOTH_RESERVATION_BYTES',
         'RETUNE_TARGET_SEGMENT_RESERVATION_BYTES','retune_request_work_counts','estimate_retune_target_bytes',
         'cents_distance','cents_ratio','build_target_lattice','build_target_schedule','lattice_at','nearest_tooth',
         'SpectralRetunePlan','SpectralRetuneResult','retune_components','inspection_payload',
         'estimate_retune_memory_bytes','make_retune_executor','submit_retune_job',
         'ChordnessError','CombTemplate','ChordnessCoefficients','ChordnessRequest','harmonic_comb',
         'templates_from_voicing_frame','evaluate_template','evaluate_union','select_templates','objective_terms',
         'ChordnessFrameDecision','ChordnessResult','apply_chordness','chordness_inspection',
         'estimate_chordness_memory_bytes','make_chordness_executor','submit_chordness_job',
         'PlacementError','NonlinearStageSpec','PlacementRequest','PlacementResult','run_placement','run_family','PLACEMENTS',
         'estimate_placement_memory_bytes','make_placement_executor','submit_placement_job','make_family_executor','submit_placement_family_job',
         'pcm_sha256','spectral_metrics','level_metrics','transient_metrics','summarize_audio','difference_metrics',
         'BandSelectiveError','BandSlotSpec','BandSelectiveRequest','BandSelectiveResult','process_band_selective']
