"""Explicit sonority and deterministic constrained voice-leading primitives."""
from .model import (HarmonyError,SonorityTone,SonoritySpec,VoiceSpec,VoicingConstraints,VoicePitch,
                    CostBreakdown,VoicingFrame,ProgressionResult)
from .engine import solve_voicing,solve_progression
from .events import progression_events,voice_event_groups,voice_phrase_plans
from .audition import HarmonyAudition,audition_progression

__all__=['HarmonyError','SonorityTone','SonoritySpec','VoiceSpec','VoicingConstraints','VoicePitch','CostBreakdown','VoicingFrame','ProgressionResult',
         'solve_voicing','solve_progression','progression_events','voice_event_groups','voice_phrase_plans','HarmonyAudition','audition_progression']
