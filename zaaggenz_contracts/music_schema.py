"""Musical intent: no synthesized data, automatic retuning or executor."""
from .schema import *


def musical():
    tempo = obj(beat=RAT, bpm=RAT)
    meter = obj(beat=RAT, numerator=integer(1, 32), denominator=enum(1, 2, 4, 8, 16, 32))
    mapping = obj(first_key=integer(0, 127), last_key=integer(0, 127),
                  middle_key=integer(0, 127), reference_key=integer(0, 127),
                  formal_period_degrees=integer(-256, 256),
                  entries=array(nullable(integer(-4096, 4096)), 1, 128))
    curve = obj(axis=enum('pitch_cents', 'brightness_hz', 'roughness_fraction', 'density_per_beat', 'gain_db'),
                unit=enum('cents', 'Hz', 'ratio', 'events/beat', 'dB'),
                interpolation=enum('step', 'linear'),
                points=array(obj(beat=RAT, value=num()), 1, 4096))
    event = obj(id=ID, beat=RAT, duration_beats=RAT, source_id=ID,
                pitch=nullable(obj(tuning_id=ID, degree=integer(-4096, 4096), detune_cents=num(-4800, 4800))),
                gain_db=num(-120, 24), gesture_id=nullable(ID),
                layer_role=enum('synthline', 'exciter', 'body', 'aux', 'sub'))
    role = obj(beat=RAT, duration_beats=RAT,
               role=enum('establish', 'repeat', 'variation', 'fakeout', 'transition', 'return'))
    return {
        'TimeMap': contract('TimeMap', sample_rate_hz=RATE, origin_sample=integer(),
                            beat_unit=const('quarter_note'), rounding=const('nearest_ties_even'),
                            tempo_segments=array(tempo, 1, 2048), meter_segments=array(meter, 1, 2048)),
        'TuningSpec': contract('TuningSpec', id=ID, reference_hz=num(0.001, 96000),
                              reference_degree=integer(-4096, 4096), period_ratio=num(1.000001, 16),
                              degree_ratios=array(num(1, 16), 1, 256), keyboard=nullable(mapping)),
        'GestureSpec': contract('GestureSpec', id=ID, duration_beats=RAT, curves=array(curve, 1, 5)),
        'PhrasePlan': contract('PhrasePlan', start_beat=RAT, end_beat=RAT, tuning_id=ID,
                              source_ids=array(ID, 1, 64, unique=True),
                              gestures=array(ref('GestureSpec'), 0, 128), events=array(event, 0, 8192),
                              roles=array(role, 0, 2048), bass_role=enum('none', 'pedal', 'moving'),
                              random=RANDOM),
    }
