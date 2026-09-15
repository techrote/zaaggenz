"""Source-preserving melodic construction for zaaggenz."""
from .model import MelodyError, NoteMode, MelodicRenderSpec, MelodicRenderResult
from .recipe import note_event, rest_event, make_phrase_plan, make_melodic_recipe, transform_melodic_recipe
from .pitch import pitch_shift_static, pitch_warp_variable
from .render import render_phrase, melodic_cache_key, make_render_executor

__all__=['MelodyError','NoteMode','MelodicRenderSpec','MelodicRenderResult','note_event','rest_event',
         'make_phrase_plan','make_melodic_recipe','transform_melodic_recipe','pitch_shift_static','pitch_warp_variable',
         'render_phrase','melodic_cache_key','make_render_executor']
