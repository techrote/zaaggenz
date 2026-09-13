"""Safe project-local mnemonic text gestures with explicit preview/apply boundaries."""
from .model import TextGestureError,MnemonicDictionary,DictionaryRegistry,VERSION
from .syntax import TextSyntaxError,parse_text,format_text,semantic_ast,MODIFIER_UNITS
from .compile import TextCompilation,compile_text,make_render_recipe
from .bundle import TextGestureBundle,make_bundle
from .presets import starter_registry

__all__=['TextGestureError','TextSyntaxError','MnemonicDictionary','DictionaryRegistry','VERSION','MODIFIER_UNITS','parse_text','format_text','semantic_ast','TextCompilation','compile_text','make_render_recipe','TextGestureBundle','make_bundle','starter_registry']
