"""Owner-approved v3 preset tiers; metadata never mutates the approved audio."""
from .model import ZaagFamilyError, canonical_sha256
from zaaggenz_contracts.legacy import adapt_parameters

IDS = ('zaag.krach-v3-open', 'zaag.krach-v3-pulse', 'zaag.krach-v3-weight', 'zaag.krach-v3-edge')
TIERS = ('primary', 'secondary', 'secondary', 'secondary')
RECIPE_HASHES = (
    'ddd6faddaa148d616f23065f7b6bb59508a126f4e3be1f84ad513b53b9552608',
    '80e76d19e2dd009e37771e5def1076f7b420bf2d52bdd60286e91bd8baf4d687',
    'bd7cd7c1c2790f7463f0396cb6d688d240b450ecc9e9e5494baab2697782bce5',
    '52cdcc3af23c2baaac37bf1f8f4a69b2b5cb69f0e99d45736f6034a350f91160')


def recipe_for(identifier):
    from .krach_retry_v3 import RECIPES
    if type(identifier) is not str or identifier not in IDS:
        raise ZaagFamilyError('unknown approved Krach preset')
    index = IDS.index(identifier)
    recipe = RECIPES[index]
    if canonical_sha256(recipe.payload()) != RECIPE_HASHES[index]:
        raise ZaagFamilyError('approved Krach recipe changed; create a new identity instead')
    return recipe


def parameters(identifier, sr=48000, bpm=190.):
    """Bounded source recipe without rendering on the interactive/UI thread."""
    from .krach_retry_v3 import rate_bpm
    from .registry import family
    recipe = recipe_for(identifier)
    bpm = rate_bpm(sr, bpm)
    k = recipe.style
    return adapt_parameters('synth', {**family(recipe.parent).synth_overrides,
        'sr': sr, 'bpm': bpm, 'beats': 1, 'beat_fill': .97,
        'noise_level': 0., 'roughness': 0., 'pitch_jitter_cents': 0., 'harmonic_lock_cents': 0., 'transient_click': 0.,
        'harmonic_count': (64,60,72,68)[k], 'harmonic_decay': (.66,.60,.60,.58)[k],
        'odd_even_ratio': (1.08,1.18,.94,1.04)[k], 'harmonic_tilt_db_per_oct': -.12,
        'sweep_semitones': (-1.2,-.75,-1.5,-.6)[k], 'sweep_tau_ms': 36.,
        'input_trim_db': -6., 'drive_db': (14.,17.,16.,18.)[k], 'shaper_mix': .78,
        'asymmetry': (.17,.13,.22,.10)[k], 'hard_clip_mix': .12,
        'wavefold': (.28,.36,.42,.24)[k], 'preemphasis': .06,
        'attack_ms': 1.5, 'decay_ms': 360., 'sustain': .06,
        'post_hp_hz': 18., 'post_lp_hz': 16500., 'peak': .90})


def validate_binding(identifier, params):
    if type(params) is not dict or params != parameters(identifier, params.get('sr'), params.get('bpm')):
        raise ZaagFamilyError('approved Krach preset/source mismatch; no silent substitution')


def render(identifier, params):
    from .krach_retry_v3 import render_source
    validate_binding(identifier, params)
    audio, info = render_source(recipe_for(identifier), params['sr'], bpm=params['bpm'])
    if info['source_parameters'] != params:
        raise ZaagFamilyError('Krach adapter and frozen renderer disagree')
    return audio


def catalogue():
    result = []
    for identifier, tier in zip(IDS, TIERS):
        recipe = recipe_for(identifier)
        result.append({'id': identifier, 'name': recipe.label,
            'label': recipe.label if tier == 'primary' else recipe.label+' — secondary', 'tier': tier,
            'protected_default': False, 'owner_approved': True,
            'recipe_sha256': canonical_sha256(recipe.payload()),
            'owner_disposition': 'favourite; first-class preset' if tier == 'primary' else 'retained; second-class processing starting point',
            'extra_distortion_applied': False, 'sample_rates_hz': [12000,48000], 'bpm_range': [60,260],
            'source_policy': 'frozen v3 renderer; no new normalization',
            'limitations': ['Compose uses its existing source-derived pitch/tail policy; audition riffs use explicit sampler transposition.']})
    return result
