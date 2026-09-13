"""Bounded deterministic expansion with one provenance record per event."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.model import fraction, derive_seed
from zaaggenz_melody import note_event, rest_event, make_phrase_plan
from zaaggenz_tuning import tuning_from_spec
from .model import GrammarError, GrammarSpec, ExpansionRequest


def _rat(value):
    return f'{value.numerator}/{value.denominator}'


def _draw(seed, label, weights):
    """Rejection-sampled SHA-256 choice; no Python PRNG/platform dependence."""
    total = sum(weights)
    limit = 2**64 - (2**64 % total)
    counter = 0
    while True:
        message = f'zaaggenz.grammar-choice-v1\0{seed}\0{label}\0{counter}'
        value = int.from_bytes(hashlib.sha256(message.encode()).digest()[:8], 'big')
        if value < limit:
            value %= total
            break
        counter += 1
    for index, weight in enumerate(weights):
        if value < weight:
            return index
        value -= weight
    raise AssertionError('unreachable weighted choice')


@dataclass(frozen=True)
class GrammarExpansion:
    phrase: Contract
    grammar_sha256: str
    request_sha256: str
    _trace_json: str

    @property
    def trace(self):
        return json.loads(self._trace_json)

    @property
    def sha256(self):
        return digest({'phrase': self.phrase.to_dict(), 'grammar_sha256': self.grammar_sha256,
                       'request_sha256': self.request_sha256, 'trace': self.trace})


def expand_grammar(grammar, request, tuning, *, manual_phrase=None):
    if not isinstance(grammar, GrammarSpec) or not isinstance(request, ExpansionRequest):
        raise GrammarError('GrammarSpec and ExpansionRequest required')
    g = grammar.to_dict()
    td = tuning.to_dict() if isinstance(tuning, Contract) else tuning
    try:
        t = tuning_from_spec(td)
    except ValueError as exc:
        raise GrammarError('valid TuningSpec required') from exc
    if not request.enabled:
        if not isinstance(manual_phrase, Contract) or manual_phrase.to_dict()['kind'] != 'PhrasePlan':
            raise GrammarError('disabled grammar requires an explicit manual PhrasePlan')
        if manual_phrase.to_dict()['tuning_id'] != t.id:
            raise GrammarError('manual phrase tuning mismatch')
        trace = [{'event_id': e['id'], 'rule': 'manual-bypass', 'degree': None if e['pitch'] is None else e['pitch']['degree']}
                 for e in manual_phrase.to_dict()['events']]
        return GrammarExpansion(manual_phrase, grammar.sha256, digest(request.to_dict()), json.dumps(trace))
    if len(t.degree_ratios) != g['period_degrees']:
        raise GrammarError('grammar period_degrees does not match active tuning')
    if request.event_count < len(g['return_path']) + 1:
        raise GrammarError('event_count must leave an entry note plus the full return path')
    hierarchy = {d['degree']: d['weight'] for d in g['degrees']}
    notes = [n for n in range(g['register']['minimum'], g['register']['maximum'] + 1)
             if n % g['period_degrees'] in hierarchy]
    cursor = notes.index(0)
    seed = derive_seed(request.seed, 'grammar.choices')
    stop = request.event_count - len(g['return_path'])
    events, trace = [], []
    step, start = fraction(request.step_beats), fraction(request.start_beat)

    def emit(relative_degree, rule, **metadata):
        i = len(events)
        event_id = f'grammar-{i:04d}'
        beat = _rat(start + i * step)
        if relative_degree is None:
            event = rest_event(event_id, beat, request.step_beats)
            hz = degree = None
        else:
            degree = request.tonic_degree + relative_degree
            hz = t.frequency(degree)
            event = note_event(event_id, beat, request.step_beats, t.id, degree, gain_db=request.gain_db)
        events.append(event)
        trace.append({'event_id': event_id, 'rule': rule, 'degree': degree,
                      'target_hz': hz, 'resting_tone': relative_degree is not None and relative_degree % g['period_degrees'] in g['resting_degrees'],
                      **metadata})

    emit(0, 'entry-tonic')
    while len(events) < stop:
        i = len(events)
        direction = request.directions[i % len(request.directions)]
        if request.rest_every and i % request.rest_every == 0:
            emit(None, 'scheduled-rest')
            continue
        kind = None
        if request.ornament_every and i % request.ornament_every == 0:
            kind = 'ornament'
        elif request.motif_every and i % request.motif_every == 0:
            kind = 'motif'
        if kind is not None:
            patterns = [m for m in g['motifs'] if m['kind'] == kind and m['direction'] in (direction, 'any')
                        and i + len(m['steps']) <= stop
                        and all(0 <= cursor + offset < len(notes) for offset in m['steps'])]
            if not patterns:
                # Short remaining windows are intentionally walks; no truncated motif.
                if any(m['kind'] == kind and i + len(m['steps']) <= stop for m in g['motifs']):
                    raise GrammarError(f'event {i}: no {kind} fits current direction/register')
                if not any(m['kind'] == kind for m in g['motifs']):
                    raise GrammarError(f'event {i}: requested {kind} but grammar has none')
            else:
                selected = patterns[_draw(seed, f'{i}.{kind}', [m['weight'] for m in patterns])]
                origin = cursor
                for position, offset in enumerate(selected['steps']):
                    emit(notes[origin + offset], kind, pattern_id=selected['id'], pattern_position=position,
                         requested_direction=direction)
                cursor = origin + selected['steps'][-1]
                continue
        if direction == 'hold':
            emit(notes[cursor], 'hold', requested_direction=direction)
            continue
        actual_direction = direction
        def candidates(d):
            key = 'ascending_steps' if d == 'up' else 'descending_steps'
            return [(cursor + entry['step'], entry['weight'] * hierarchy[notes[cursor + entry['step']] % g['period_degrees']])
                    for entry in g[key] if 0 <= cursor + entry['step'] < len(notes)]
        choices = candidates(direction)
        reflected = False
        if not choices and g['boundary'] == 'reflect':
            actual_direction = 'down' if direction == 'up' else 'up'
            choices = candidates(actual_direction)
            reflected = True
        if not choices:
            raise GrammarError(f'event {i}: no legal {direction} transition in register')
        old = cursor
        selected = _draw(seed, f'{i}.walk', [weight for _, weight in choices])
        cursor = choices[selected][0]
        emit(notes[cursor], 'directional-step', requested_direction=direction,
             realised_direction=actual_direction, reflected=reflected, scale_index_step=cursor - old,
             selected_weight=choices[selected][1], candidate_weight_sum=sum(weight for _, weight in choices))
    for index, degree in enumerate(g['return_path']):
        emit(degree, 'return-path', path_position=index)
    phrase = make_phrase_plan(t.id, events, start_beat=request.start_beat,
                              end_beat=_rat(start + request.event_count * step), seed=request.seed)
    return GrammarExpansion(phrase, grammar.sha256, digest(request.to_dict()), json.dumps(trace, allow_nan=False))
