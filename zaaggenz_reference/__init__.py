"""Private-reference registry, verification, descriptors and annotations."""
from .registry import load_registry, load_locators, resolve_assets, ReferenceError
from .analysis import descriptor_pcm, analyse_file, compare_planning
from .annotation import validate_annotation
__all__=['load_registry','load_locators','resolve_assets','ReferenceError','descriptor_pcm','analyse_file','compare_planning','validate_annotation']
