"""Bounded offline DSP graph execution, nonlinear and band-selective processing primitives."""
from .graph import GraphError, execute_graph, apply_output_policy
from .multiband import split_bands, route_effect_deltas, multiband_gain
from .legacy import graphify_legacy_recipe, render_recipe, RenderResult
from .antialias import (AntialiasError,SUPPORTED_OVERSAMPLE,REFERENCE_OVERSAMPLE,FILTER_POLICY_ID,
                        filter_metadata,oversampled_shaper,reference_shaper,reference_error)
from .dynamics import DynamicsError,CompressionSpec,CompressionResult,compress
from .bitcrush import BitcrushError,BitcrushSpec,BitcrushResult,bitcrush
from .band_router import BAND_NAMES,BandDeltaReport,filter_metadata as band_filter_metadata,route_band_processors
from .band_effects import BandEffectError,BandEffectSpec,BandEffectResult,process_band_effects

__all__=['GraphError','execute_graph','apply_output_policy','split_bands','route_effect_deltas','multiband_gain',
         'graphify_legacy_recipe','render_recipe','RenderResult','AntialiasError','SUPPORTED_OVERSAMPLE',
         'REFERENCE_OVERSAMPLE','FILTER_POLICY_ID','filter_metadata','oversampled_shaper','reference_shaper','reference_error',
         'DynamicsError','CompressionSpec','CompressionResult','compress','BitcrushError','BitcrushSpec','BitcrushResult','bitcrush',
         'BAND_NAMES','BandDeltaReport','band_filter_metadata','route_band_processors','BandEffectError','BandEffectSpec','BandEffectResult','process_band_effects']
