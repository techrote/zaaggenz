"""ZG-024b bounded deterministic search-strategy research."""
from .strategies import (METHODS, StrategySpec, StrategyResult, ResearchCheckpoint,
    ResearchInterrupted, ResearchResumeDivergence, run_strategy, submit_strategy_job)
from .fixtures import (CORE_NAMES, SEARCH_SEEDS, SENTINEL_NAME, research_fixture,
    normalized_parameter_error, nonidentifiable_manifold_error)

__all__ = ['METHODS', 'StrategySpec', 'StrategyResult', 'ResearchCheckpoint',
    'ResearchInterrupted', 'ResearchResumeDivergence', 'run_strategy',
    'submit_strategy_job', 'CORE_NAMES', 'SEARCH_SEEDS', 'SENTINEL_NAME',
    'research_fixture', 'normalized_parameter_error', 'nonidentifiable_manifold_error']
