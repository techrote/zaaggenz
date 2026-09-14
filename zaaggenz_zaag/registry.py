from __future__ import annotations
from .model import ProtectedAnchor,ZaagFamilyRecipe,ZaagMacros,ExpertControls,canonical_sha256

LOCKED_BLOOM=ProtectedAnchor(
    id='locked_bloom',
    canonical_json_sha256='6a6e5a55f04f978e57e90b9e582d2b830b3d82192aec7d0f727112ef75b5afe2',
    invariants={'f0_hz':48.0,'harmonic_count':49,'noise_level':0.0,'roughness':0.0},
    render_hashes={'ci_12k':'09f28bbf9ff7a3d559fee9db612103e44021c0cb2a6a3f4f91586fe3985a5ed0',
                   'full_rate_48k':'25eabbe29b4ea4a2930acd700a32af141cfe72337b1b88edc7dee3476d09fe65'})

# These are new experimental sources. They deliberately do not copy/reconstruct locked_bloom.
_COMMON={'f0_hz':48.0,'beats':1,'beat_fill':.95,'sweep_semitones':-1.15,'sweep_tau_ms':54.,'pitch_jitter_cents':2.,
         'harmonic_count':43,'harmonic_decay':.78,'odd_even_ratio':1.75,'harmonic_tilt_db_per_oct':-1.1,
         'roughness':0.0,'noise_level':0.0,'drive_db':9.5,'input_trim_db':-10.,'shaper_mix':.64,
         'hard_clip_mix':.34,'hard_clip_level':.9,'wavefold':.46,'preemphasis':.1,'attack_ms':1.1,
         'decay_ms':275.,'sustain':.04,'transient_click':.045,'post_hp_hz':24.,'post_lp_hz':18000.,'peak':.94}

def _s(**kwargs):return {**_COMMON,**kwargs}

def _f(id,label,intent,macros,synth,expert,pitch,tuning,limitations,classification='candidate'):
    return ZaagFamilyRecipe(id,label,intent,classification,macros,synth,expert,pitch,tuning,tuple(limitations))

FAMILIES=(
 _f('zaag.relaxed-punch','Relaxed Punch','Longer attack/decay relaxation while retaining a nonlinear source edge.',
    ZaagMacros(attack_relax=.92,grit=.34),_s(attack_ms=4.4,decay_ms=345.,sweep_semitones=-.8,hard_clip_mix=.28,wavefold=.34,seed=2201),
    ExpertControls(grit_drive_db=4.,grit_mix=.18,grit_oversample=4,pitch_ratio_min=.55,pitch_ratio_max=1.8,quality_cost='medium'),
    (27.,96.),'Best as a low/mid source; source-derived pitch motion up to roughly +1 octave remains the intended zone.',
    ['Softened front edge can lose bite in very dense rolls.','Not designed as a bright lead above the documented pitch range.']),
 _f('zaag.vowel-sway','Vowel Sway','Source-preserving zaag with a moving resonant upper-mid emphasis for vowel-like articulation.',
    ZaagMacros(vowel_motion=.94,attack_relax=.28,grit=.2),_s(harmonic_count=47,harmonic_decay=.73,odd_even_ratio=1.9,seed=2202),
    ExpertControls(formant_start_hz=760.,formant_end_hz=2100.,formant_q=2.8,formant_boost_db=5.5,grit_drive_db=3.,grit_mix=.12,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.,quality_cost='high'),
    (24.,110.),'Works with 12-EDO and non-octave/local tunings provided source-derived ratios stay inside the declared pitch ratio range.',
    ['The formant motion is an engineered spectral gesture, not a vocal-formant model.','Strong chord stacks can make the moving resonance crowded.']),
 _f('zaag.upper-bounce','Upper Bounce','Upper partial group pulses on a slower beat while the low/source body remains continuous.',
    ZaagMacros(upper_bounce=1.,grit=.3,harmonic_motion=.25),_s(decay_ms=255.,harmonic_count=45,seed=2203),
    ExpertControls(upper_bounce_depth_db=5.5,upper_bounce_rate_beats=2.,grit_drive_db=5.,grit_mix=.16,grit_oversample=4,pitch_ratio_min=.55,pitch_ratio_max=2.2,quality_cost='medium'),
    (28.,118.),'Intended for half-/quarter-rate upper-group movement above a persistent lower body.',
    ['Upper bounce is amplitude motion, not a sidechain model.','Very fast BPM or extreme pitch-up can make the pulse overly bright.']),
 _f('zaag.complementary-pulse','Complementary Pulse','Opposed lower/upper envelopes exchange emphasis without dropping the full source line.',
    ZaagMacros(complementary_motion=1.,upper_bounce=.28,attack_relax=.35),_s(harmonic_decay=.8,hard_clip_mix=.3,seed=2204),
    ExpertControls(complementary_depth_db=4.5,upper_bounce_depth_db=1.5,upper_bounce_rate_beats=4.,pitch_ratio_min=.5,pitch_ratio_max=2.,quality_cost='medium'),
    (24.,105.),'Useful for call/response-like timbral movement while pitch remains source-derived.',
    ['Opposed envelopes can feel hollow at their crossing point on sparse notes.','Not a substitute for independent musical layers.']),
 _f('zaag.grit-skip','Grit Skip','Controlled nonlinear grit plus light sample-hold texture, bounded so pitch identity remains available.',
    ZaagMacros(grit=.9,upper_bounce=.32),_s(drive_db=13.,shaper_mix=.72,hard_clip_mix=.48,wavefold=.68,seed=2205),
    ExpertControls(grit_drive_db=11.,grit_mix=.42,grit_oversample=4,bit_depth=8,hold_samples=2,bitcrush_wet=.18,upper_bounce_depth_db=1.8,pitch_ratio_min=.6,pitch_ratio_max=1.75,quality_cost='high'),
    (31.,84.),'Keep closer to the source pitch; this family intentionally spends more spectral headroom on texture.',
    ['Can alias intentionally through the sample-hold stage.','Dense transposition stacks can obscure melodic identity faster than the cleaner families.']),
 _f('zaag.harmonic-turn','Harmonic Turn','Harmonic-rich source intended for explicit interval/chord movement in source-preserving phrase manifests.',
    ZaagMacros(harmonic_motion=1.,vowel_motion=.28,grit=.24),_s(harmonic_count=55,harmonic_decay=.68,odd_even_ratio=1.95,hard_clip_mix=.38,wavefold=.5,seed=2206),
    ExpertControls(formant_start_hz=1100.,formant_end_hz=1650.,formant_q=2.,formant_boost_db=2.2,grit_drive_db=4.,grit_mix=.14,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.25,quality_cost='high'),
    (24.,108.),'Designed for explicit harmonic progression and interval layering; target relationships stay visible in the arrangement manifest.',
    ['Rich upper structure can become dense under wide chords.','Harmonic-motion macro does not imply any preferred chord vocabulary.']),
 _f('contrast.piep','Piep Contrast','Intentionally thin bright contrast for audition discrimination; not a zaag default candidate.',
    ZaagMacros(),_s(harmonic_count=7,harmonic_decay=1.55,odd_even_ratio=1.,drive_db=2.,shaper_mix=.12,hard_clip_mix=0.,wavefold=0.,attack_ms=.3,decay_ms=120.,sustain=.01,post_lp_hz=7000.,seed=2291),
    ExpertControls(pitch_ratio_min=.7,pitch_ratio_max=2.5,quality_cost='low'),(36.,140.),'Contrast only; deliberately favours sparse bright partial structure.',
    ['Intentional negative/control condition.','Do not select as a zaag default from low-noise metrics.'],'contrast'),
 _f('contrast.noise-wall','Noise Wall Contrast','Intentionally noisy/rough comparison condition.',
    ZaagMacros(grit=1.),_s(roughness=.62,noise_level=.22,noise_attack_ms=1.,noise_decay_ms=240.,drive_db=16.,hard_clip_mix=.56,wavefold=.7,seed=2292),
    ExpertControls(grit_drive_db=14.,grit_mix=.55,grit_oversample=2,bit_depth=7,hold_samples=3,bitcrush_wet=.28,pitch_ratio_min=.65,pitch_ratio_max=1.6,quality_cost='high'),(31.,76.),'Contrast only; deliberately degrades stable pitch/timbre cues.',
    ['Intentional negative/control condition.','High roughness/noise is not interpreted as excitement or preference.'],'contrast'),
 _f('contrast.overflattened','Overflattened Contrast','Deliberately over-even harmonic balance used to reveal loss of source contour.',
    ZaagMacros(harmonic_motion=.1),_s(harmonic_count=60,harmonic_decay=.18,odd_even_ratio=1.,harmonic_tilt_db_per_oct=0.,drive_db=5.,hard_clip_mix=.08,wavefold=.05,seed=2293),
    ExpertControls(pitch_ratio_min=.55,pitch_ratio_max=1.8,quality_cost='medium'),(28.,86.),'Contrast only; deliberately over-distributes energy across harmonic groups.',
    ['Intentional negative/control condition.','Low spectral flatness or harmonic fit must not be treated as preference evidence.'],'contrast'))

_BY_ID={x.id:x for x in FAMILIES}

def family(id):
    try:return _BY_ID[id]
    except KeyError as exc:raise KeyError('unknown zaag family '+str(id)) from exc

def candidates():return tuple(x for x in FAMILIES if x.classification=='candidate')
def contrasts():return tuple(x for x in FAMILIES if x.classification=='contrast')
def registry_payload():return {'kind':'ZaagFamilyRegistry','version':'1.0.0','protected_anchor':LOCKED_BLOOM.to_dict(),'families':[x.to_dict() for x in FAMILIES],'new_default':None,'owner_approval_required':True}
def registry_sha256():return canonical_sha256(registry_payload())
