from __future__ import annotations
from .model import ProtectedAnchor,ZaagFamilyRecipe,ZaagMacros,ExpertControls,canonical_sha256

LOCKED_BLOOM=ProtectedAnchor(
    id='locked_bloom',
    canonical_json_sha256='6a6e5a55f04f978e57e90b9e582d2b830b3d82192aec7d0f727112ef75b5afe2',
    invariants={'f0_hz':48.0,'harmonic_count':49,'noise_level':0.0,'roughness':0.0},
    render_hashes={'ci_12k':'09f28bbf9ff7a3d559fee9db612103e44021c0cb2a6a3f4f91586fe3985a5ed0',
                   'full_rate_48k':'25eabbe29b4ea4a2930acd700a32af141cfe72337b1b88edc7dee3476d09fe65'})

# Owner-rejected ZG-022 v1 audition recipes remain preserved in PR #80/#184
# artifacts and repository history. These replacement candidate IDs deliberately
# do not rewrite that historical evidence and do not reconstruct locked_bloom.
_COMMON={'f0_hz':48.0,'beats':1,'beat_fill':.96,'sweep_semitones':-3.2,'sweep_tau_ms':43.,'pitch_jitter_cents':7.,
         'harmonic_count':55,'harmonic_decay':.62,'odd_even_ratio':1.9,'harmonic_tilt_db_per_oct':-.25,
         'roughness':.10,'noise_level':.015,'noise_attack_ms':.7,'noise_decay_ms':210.,
         'drive_db':18.,'input_trim_db':-9.,'shaper_mix':.78,'asymmetry':.12,
         'hard_clip_mix':.48,'hard_clip_level':.82,'wavefold':.74,'preemphasis':.24,'attack_ms':.65,
         'decay_ms':310.,'sustain':.05,'transient_click':.08,'transient_ms':2.2,
         'post_hp_hz':24.,'post_lp_hz':19000.,'peak':.94}

def _s(**kwargs):return {**_COMMON,**kwargs}

def _f(id,label,intent,macros,synth,expert,pitch,tuning,limitations,classification='candidate'):
    return ZaagFamilyRecipe(id,label,intent,classification,macros,synth,expert,pitch,tuning,tuple(limitations))

FAMILIES=(
 _f('zaag.bloom-bark','Bloom Bark','A slightly relaxed front edge that blooms into an asymmetric folded bark instead of a clean tonal twang.',
    ZaagMacros(attack_relax=.72,grit=.68),_s(attack_ms=4.8,decay_ms=420.,sweep_semitones=-2.3,harmonic_count=58,harmonic_decay=.55,roughness=.18,drive_db=21.,shaper_mix=.84,asymmetry=.2,hard_clip_mix=.56,wavefold=.96,preemphasis=.34,seed=3221),
    ExpertControls(grit_drive_db=9.,grit_mix=.34,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.,quality_cost='high'),
    (25.,102.),'Low/mid brutal source; allow the slower front edge to speak before dense rolls or large upward transposition.',
    ['Deliberately less click-led than the other replacements.','Very dense repeated notes can mask the attack-to-bark transition.']),
 _f('zaag.formant-snarl','Formant Snarl','Aggressive moving resonances drive a saturated vowel/snarl transition while preserving the authored root.',
    ZaagMacros(vowel_motion=1.,attack_relax=.18,grit=.62),_s(harmonic_count=64,harmonic_decay=.50,odd_even_ratio=2.15,roughness=.16,drive_db=20.,shaper_mix=.86,hard_clip_mix=.52,wavefold=.84,seed=3222),
    ExpertControls(formant_start_hz=700.,formant_end_hz=2600.,formant_q=4.8,formant_boost_db=10.5,grit_drive_db=8.,grit_mix=.3,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.,quality_cost='high'),
    (24.,108.),'Use where the source should read as a moving snarl rather than a static bright resonance; keep active formants inside the exact sample-rate contract.',
    ['Strong resonances can crowd wide chord stacks.','Formant movement is an engineered spectral gesture, not a vocal model.']),
 _f('zaag.upper-chop','Upper Chop','Continuous low body with a brutally chopped and re-excited upper band for unmistakable bounce.',
    ZaagMacros(upper_bounce=1.,grit=.72,harmonic_motion=.2),_s(harmonic_count=60,harmonic_decay=.57,roughness=.13,drive_db=22.,shaper_mix=.85,hard_clip_mix=.6,wavefold=.9,decay_ms=285.,seed=3223),
    ExpertControls(upper_bounce_depth_db=8.,upper_bounce_rate_beats=.5,grit_drive_db=10.,grit_mix=.36,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.1,quality_cost='high'),
    (27.,112.),'Designed for fast upper-band rhythmic articulation over a legible low source body.',
    ['The hard upper chop is intentionally obvious rather than transparent.','At extreme BPM the upper articulation can turn into a bright buzz.']),
 _f('zaag.split-maul','Split Maul','Opposed low/high motion slams the spectral halves against each other instead of gently crossfading them.',
    ZaagMacros(complementary_motion=1.,upper_bounce=.42,grit=.68),_s(harmonic_count=58,harmonic_decay=.66,odd_even_ratio=2.4,roughness=.14,drive_db=23.,shaper_mix=.84,hard_clip_mix=.58,wavefold=.82,seed=3224),
    ExpertControls(complementary_depth_db=8.5,upper_bounce_depth_db=2.8,upper_bounce_rate_beats=1.,grit_drive_db=10.,grit_mix=.34,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.,quality_cost='high'),
    (24.,104.),'Use for alternating body/teeth emphasis where both halves must still belong to one source.',
    ['Spectral alternation is deliberately coarse and can dominate sparse sustained notes.','Not a substitute for two independently arranged layers.']),
 _f('zaag.crushed-teeth','Crushed Teeth','Hard nonlinear edge, low-bit sample-hold teeth and upper-band re-excitation produce an intentionally destructive but still pitched zaag.',
    ZaagMacros(grit=1.,upper_bounce=.18),_s(harmonic_count=62,harmonic_decay=.5,roughness=.28,noise_level=.04,drive_db=26.,shaper_mix=.9,asymmetry=.24,hard_clip_mix=.72,hard_clip_level=.76,wavefold=1.,preemphasis=.38,seed=3225),
    ExpertControls(grit_drive_db=18.,grit_mix=.72,grit_oversample=4,bit_depth=5,hold_samples=3,bitcrush_wet=.5,pitch_ratio_min=.55,pitch_ratio_max=2.,quality_cost='high'),
    (29.,88.),'Keep near the source register when pitch identity matters; this family intentionally spends substantial spectral headroom on teeth and alias texture.',
    ['Deliberate sample-hold/quantisation images are part of the sound.','Dense transposition stacks can lose pitch clarity faster than the other candidates.']),
 _f('zaag.harmonic-rip','Harmonic Rip','Dense partial structure is torn by short comb offsets and moving ring-like sidebands for a metallic harmonic rip that remains phraseable.',
    ZaagMacros(harmonic_motion=1.,vowel_motion=.24,grit=.78),_s(harmonic_count=74,harmonic_decay=.44,odd_even_ratio=2.2,harmonic_tilt_db_per_oct=.15,roughness=.12,drive_db=22.,shaper_mix=.86,hard_clip_mix=.62,wavefold=.94,seed=3226),
    ExpertControls(formant_start_hz=1050.,formant_end_hz=1850.,formant_q=2.4,formant_boost_db=2.8,grit_drive_db=11.,grit_mix=.4,grit_oversample=4,pitch_ratio_min=.5,pitch_ratio_max=2.25,quality_cost='high'),
    (24.,106.),'Designed for explicit interval/progression use where a metallic rip should follow pitch rather than become an unpitched effect.',
    ['Short-comb coloration becomes denser in wide chords.','The tearing sidebands are intentionally more metallic than the other candidates.']),
 _f('contrast.piep','Piep Contrast','Intentionally sparse, bright and clean comparison condition: the anti-brutal thin-piep endpoint.',
    ZaagMacros(),_s(harmonic_count=3,harmonic_decay=2.3,odd_even_ratio=1.,roughness=0.,noise_level=0.,drive_db=0.,shaper_mix=.04,hard_clip_mix=0.,wavefold=0.,preemphasis=0.,attack_ms=.2,decay_ms=105.,sustain=.005,transient_click=.015,post_lp_hz=6000.,seed=3291),
    ExpertControls(pitch_ratio_min=.7,pitch_ratio_max=2.5,quality_cost='low'),(36.,140.),'Contrast only; deliberately favours a sparse clean bright partial structure.',
    ['Intentional negative/control condition.','Do not select as a zaag default from cleanliness metrics.'],'contrast'),
 _f('contrast.noise-wall','Noise Wall Contrast','Intentionally pitch-obscuring rough/noise wall used to bracket brutality without melodic identity.',
    ZaagMacros(grit=1.),_s(harmonic_count=36,harmonic_decay=.7,roughness=.9,noise_level=.45,noise_attack_ms=.2,noise_decay_ms=300.,drive_db=28.,shaper_mix=.94,hard_clip_mix=.82,hard_clip_level=.7,wavefold=1.,preemphasis=.4,seed=3292),
    ExpertControls(grit_drive_db=20.,grit_mix=.78,grit_oversample=2,bit_depth=4,hold_samples=4,bitcrush_wet=.58,pitch_ratio_min=.65,pitch_ratio_max=1.6,quality_cost='high'),(31.,76.),'Contrast only; brutality is maximised while stable pitch/timbre cues are deliberately degraded.',
    ['Intentional negative/control condition.','High roughness/noise is not interpreted as excitement or preference.'],'contrast'),
 _f('contrast.overflattened','Overflattened Contrast','Deliberately over-even dense harmonic slab used to expose loss of contour despite abundant upper energy.',
    ZaagMacros(harmonic_motion=.1),_s(harmonic_count=80,harmonic_decay=.08,odd_even_ratio=1.,harmonic_tilt_db_per_oct=0.,roughness=.03,drive_db=12.,shaper_mix=.68,hard_clip_mix=.55,wavefold=.18,preemphasis=.05,seed=3293),
    ExpertControls(pitch_ratio_min=.55,pitch_ratio_max=1.8,quality_cost='medium'),(28.,86.),'Contrast only; deliberately spreads energy across harmonic groups with little authored contour.',
    ['Intentional negative/control condition.','Harmonic density alone must not be treated as preference evidence.'],'contrast'))

_BY_ID={x.id:x for x in FAMILIES}

def family(id):
    try:return _BY_ID[id]
    except KeyError as exc:raise KeyError('unknown zaag family '+str(id)) from exc

def candidates():return tuple(x for x in FAMILIES if x.classification=='candidate')
def contrasts():return tuple(x for x in FAMILIES if x.classification=='contrast')
def registry_payload():return {'kind':'ZaagFamilyRegistry','version':'1.0.0','protected_anchor':LOCKED_BLOOM.to_dict(),'families':[x.to_dict() for x in FAMILIES],'new_default':None,'owner_approval_required':True}
def registry_sha256():return canonical_sha256(registry_payload())
