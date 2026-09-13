"""The grammar recipe uses the existing bounded scheduler and revision gate."""
from __future__ import annotations
import math
from zaaggenz_contracts.music import beat_to_sample
from zaaggenz_jobs import JobClass
from zaaggenz_melody import MelodicRenderSpec, make_render_executor
from .model import GrammarError
from .recipe import GrammarRecipe


def grammar_render_memory(recipe):
    """Conservative admission estimate, not an operating-system RSS guarantee."""
    if not isinstance(recipe, GrammarRecipe):
        raise GrammarError('GrammarRecipe required')
    d = recipe.render_recipe.to_dict()
    tm, phrase, params = d['time_map'], d['phrase'], d['source']['params']
    nominal = beat_to_sample(tm, phrase['end_beat']) - beat_to_sample(tm, phrase['start_beat'])
    source = math.ceil(params['sr'] * 60 / params['bpm'] * params['beat_fill'])
    # float64 accumulation/copies, pitch-shift working arrays and a fixed margin.
    return 16 * 1024**2 + (nominal + source) * 96 + source * 512


def submit_grammar_render(bundle, scheduler):
    estimate = grammar_render_memory(bundle)
    recipe, revision = bundle.render_recipe, bundle.project.head
    return scheduler.submit(JobClass.RENDER, revision,
                            make_render_executor(recipe, MelodicRenderSpec(), revision),
                            estimated_memory_bytes=estimate)
