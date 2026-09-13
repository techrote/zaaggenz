"""Calibrated evidence-labelled descriptors; never a pleasure or biochemical score."""
from .model import DescriptorError, DescriptorObservation, DescriptorBundle, descriptor_catalogue, observation, feature_projection
from .audio import pcm_asset, whole_support, rms_observation, periodicity_observations, envelope_observations, occupancy_observation
from .components import harmonicity_observation, roughness_observation, target_comb_observations, component_observations
from .analyse import DescriptorAnalysisSpec, DescriptorAnalysis, analyse_descriptors

__all__=['DescriptorError','DescriptorObservation','DescriptorBundle','descriptor_catalogue','observation','feature_projection',
         'pcm_asset','whole_support','rms_observation','periodicity_observations','envelope_observations','occupancy_observation',
         'harmonicity_observation','roughness_observation','target_comb_observations','component_observations',
         'DescriptorAnalysisSpec','DescriptorAnalysis','analyse_descriptors']
