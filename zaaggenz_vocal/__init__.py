"""Optional local vocal-gesture capture with confidence, abstention and editable correction."""
from .model import VocalCaptureError,VocalAnalysis,VocalEdit
from .analysis import analyse_vocal
from .edit import make_edit,update_segment,mark_source_discarded,compile_edit,make_render_recipe,VocalCompilation
from .store import SessionAudioStore,decode_wav_bytes,encode_wav_bytes
__all__=['VocalCaptureError','VocalAnalysis','VocalEdit','analyse_vocal','make_edit','update_segment','mark_source_discarded','compile_edit','make_render_recipe','VocalCompilation','SessionAudioStore','decode_wav_bytes','encode_wav_bytes']
