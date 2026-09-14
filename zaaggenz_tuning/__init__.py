"""Explicit tuning, timbre-dependent dissonance and bounded adaptive tuning primitives."""
from .core import (Tuning, KeyboardMap, TuningError, cents_to_ratio, ratio_to_cents,
                   frequency_for_degree, transpose_frequency, analyse_frequency,
                   tuning_from_spec, tuning_to_spec)
from .scala import parse_scl, export_scl, parse_kbm, export_kbm, load_scala_tuning
from .fixtures import fixture_pack
from .pitch import PitchTarget, resolve_pitch_target
from .dissonance_model import (METHOD_ID as DISSONANCE_METHOD_ID,METHOD_VERSION as DISSONANCE_VERSION,
                               DissonanceError,DissonanceModelSpec,TimbreSpectrum,IntervalGrid)
from .dissonance_curve import (InteractionObservation,IntervalCandidate,DissonanceCurve,interaction_roughness,
                               dissonance_curve,local_minima,sensitivity_candidates)
from .dissonance_source import spectrum_from_partial_bundle,harmonic_spectrum
from .adaptive_model import (ADAPTIVE_METHOD_ID,ADAPTIVE_VERSION,AdaptiveVoice,AdaptiveWeights,
                             AdaptiveTuningRequest,AdaptiveState)
from .adaptive_engine import (PairPrediction,AdaptiveProposal,propose_adaptive_tuning,commit_proposal,reject_proposal)
from .adaptive_export import candidate_tuning_set,ab_recipe
from .adaptive_jobs import (make_dissonance_map_executor,submit_dissonance_map_job,
                            make_adaptive_tuning_executor,submit_adaptive_tuning_job)

__all__=['Tuning','KeyboardMap','TuningError','cents_to_ratio','ratio_to_cents','frequency_for_degree',
         'transpose_frequency','analyse_frequency','tuning_from_spec','tuning_to_spec','parse_scl','export_scl',
         'parse_kbm','export_kbm','load_scala_tuning','fixture_pack','PitchTarget','resolve_pitch_target',
         'DISSONANCE_METHOD_ID','DISSONANCE_VERSION','DissonanceError','DissonanceModelSpec','TimbreSpectrum','IntervalGrid',
         'InteractionObservation','IntervalCandidate','DissonanceCurve','interaction_roughness','dissonance_curve','local_minima',
         'sensitivity_candidates','spectrum_from_partial_bundle','harmonic_spectrum','ADAPTIVE_METHOD_ID','ADAPTIVE_VERSION',
         'AdaptiveVoice','AdaptiveWeights','AdaptiveTuningRequest','AdaptiveState','PairPrediction','AdaptiveProposal',
         'propose_adaptive_tuning','commit_proposal','reject_proposal','candidate_tuning_set','ab_recipe',
         'make_dissonance_map_executor','submit_dissonance_map_job','make_adaptive_tuning_executor','submit_adaptive_tuning_job']
