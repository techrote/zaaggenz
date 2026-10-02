"""NYQ-001 contract/oracle, identity, admission and legacy boundary regressions."""
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace
from decimal import Decimal, getcontext, localcontext
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import random
import unittest

from zaaggenz_contracts import Contract, ContractError, digest, schema
from zaaggenz_contracts.examples import examples
from zaaggenz_contracts.legacy import freeze_legacy
from zaaggenz_contracts.rack import empty_rack, processor_definition
from zaaggenz_contracts.registry import node_definition
from zaaggenz_contracts.nyquismic import (
    VERSION, MAX_RATE_HZ, MIN_RATE_HZ, MIN_SPACING_S, MAX_EVENTS, MAX_TIME_S,
    MAX_POINTS, MAX_STAGES, MAX_LANES, MAX_RESETS, MAX_FILTER_TAPS,
    VirtualRate, RateReference, Point, Reset, ModulationRoute, RateQuantizer,
    JitterSpec, ClockSpec, SonicSpec, PlaybackMap, EvaluationPolicy, ResourceBudget,
    RenderIdentity, RackBoundary, UnsupportedNyquismic, event_seed,
    clock_cell_value, bind_render_identity, qtext,
)
from zaaggenz_contracts.nyquismic_clock import (
    ClockPlan, ClockCheckpoint, ClockCancelled, source_time, admit_foundation,
)
from nyquismic_oracles import fixture_bytes, bisected_ramp, constant

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).parent / 'fixtures'
ORACLE_SHA256 = 'b42b2d9988df822169d8fd6e02a28dd208eff2b1e0ddf4a2d15df13c6c9ee5bd'
GENERATOR_SHA256 = 'c700d12382ca1d55402f37d86376f5d625d44ed37cdedccdb21474519785c8b2'
LEGACY_SHA256 = 'a0717357a33a5f88e398ec9b5a8c524d2d3e60782a4bfa1369f3336ebf977b18'


def rate(value):
    return VirtualRate(qtext(Fraction(value)))


def clock(value='8', **kwargs):
    return ClockSpec(rate=rate(value), **kwargs)


def sonic(value='8', **kwargs):
    return SonicSpec(clock=clock(value), **kwargs)


def asset(channels=1):
    data=examples()['AudioAssetRef']
    data.update(channels=channels,channel_layout='mono' if channels==1 else 'stereo-lr')
    return Contract(data)


def bound(spec=None, evaluation=None):
    return bind_render_identity(sonic() if spec is None else spec,
                                EvaluationPolicy() if evaluation is None else evaluation,
                                input_asset=asset(1 if spec is None else spec.channels), source_revision_sha256='2'*64,
                                rack_revision_sha256='3'*64, graph_revision_sha256='4'*64,
                                context_sha256='5'*64, delivery_rate_hz=48000,
                                start_s='0/1', end_s='1/1')


class NyquismicOracles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frozen = json.loads((FIXTURES / 'nyquismic-v1.json').read_text())

    def test_frozen_independent_fixture_and_generator(self):
        saved = (FIXTURES / 'nyquismic-v1.json').read_bytes()
        self.assertEqual(hashlib.sha256(saved).hexdigest(), ORACLE_SHA256)
        self.assertEqual(saved, fixture_bytes())
        source = (Path(__file__).parent / 'nyquismic_oracles.py').read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), GENERATOR_SHA256)
        self.assertNotIn(b'zaaggenz_contracts', source)
        self.assertNotIn(b'zaaggenz_dsp', source)

    def test_all_frozen_clock_oracles(self):
        for fixture in self.frozen['clock_cases']:
            with self.subTest(name=fixture['name']):
                kwargs = {'phase_cycles': qtext(Fraction(fixture.get('phase', '0')))}
                if fixture['kind'] == 'ramp':
                    final = Fraction(fixture['rate']) + Fraction(fixture['slope']) * Fraction(fixture['extent'])
                    kwargs.update(points_hz=(Point(qtext(Fraction(fixture['extent'])), qtext(final)),), interpolation='linear')
                if fixture['kind'] == 'step':
                    kwargs['points_hz'] = (Point(fixture['step_time'], qtext(Fraction(fixture['next_rate']))),)
                if fixture['kind'] == 'reset':
                    kwargs['resets'] = (Reset(fixture['reset_time'], qtext(Fraction(fixture['reset_phase']))),)
                spec = clock(fixture['rate'], **kwargs)
                plan = ClockPlan(spec, qtext(Fraction(fixture['extent'])))
                events = plan.events()
                self.assertEqual(len(events), len(fixture['events']))
                self.assertEqual(plan.event_count, len(events))
                for index, (actual, expected) in enumerate(zip(events, fixture['events'])):
                    self.assertEqual(actual.index, index)
                    self.assertEqual(actual.epoch, expected.get('epoch', 0))
                    self.assertEqual(actual.crossing, expected['crossing'])
                    expected_time = float(Decimal(expected['time_s']))
                    tolerance = self.frozen['time_abs_tolerance_s'] + self.frozen['time_ulps'] * math.ulp(expected_time)
                    self.assertLessEqual(abs(actual.time_s - expected_time), tolerance)
                self.assertTrue(all(a.time_s < b.time_s for a, b in zip(events, events[1:])))

    def test_independent_tiny_slope_bisection_not_period_recurrence(self):
        spec = clock('8', points_hz=(Point('1/1', '8000000001/1000000000'),), interpolation='linear')
        events = ClockPlan(spec, '1/1').events()
        for event in events:
            wanted = bisected_ramp('8', '1/1000000000', str(event.crossing), '1')
            self.assertAlmostEqual(event.time_s, float(wanted), delta=2e-12)
        fast = clock('4', points_hz=(Point('1/1', '12/1'),), interpolation='linear')
        first_after_zero = ClockPlan(fast, '1/1').events()[1].time_s
        self.assertGreater(abs(first_after_zero - 1/4), .04)

    def test_random_constant_rationals_independent_fraction_oracle(self):
        rng = random.Random(250)
        for _ in range(80):
            f = Fraction(rng.randint(1, 2000), rng.randint(1, 100))
            phase = Fraction(rng.randint(0, 99), 100)
            spec = clock(f, phase_cycles=qtext(phase))
            actual = ClockPlan(spec, '1/1').events()
            expected = constant(str(f), str(phase), '1')
            self.assertEqual([e.crossing for e in actual], [k for k, _ in expected])
            self.assertEqual([e.time_s for e in actual], [float(t) for _, t in expected])

    def test_exact_ramp_integral_and_right_continuous_step(self):
        ramp = ClockPlan(clock('4', points_hz=(Point('1/1', '12/1'),), interpolation='linear'), '1/1')
        self.assertEqual(ramp.phase_at('1/2'), (0, Fraction(3)))
        self.assertEqual(ramp.phase_at('1/1'), (0, Fraction(8)))
        step = ClockPlan(clock('4', points_hz=(Point('1/2', '8/1'),)), '1/1')
        self.assertEqual(step.phase_at('1/2'), (0, Fraction(2)))
        self.assertEqual(step.phase_at('3/4'), (0, Fraction(4)))

    def test_static_alias_fixture_independent_discrete_tone_samples(self):
        for case in self.frozen['static_alias_cases']:
            tone, f = Fraction(case['tone_hz']), Fraction(case['virtual_hz'])
            signed = (tone + f/2) % f - f/2
            self.assertEqual(abs(signed), Fraction(case['magnitude_alias_hz']))
            # This checks analytic source values at uniform events, NOT a claim
            # that NYQ-001 has rendered/reconstructed audio or anti-aliased it.
            for k in range(32):
                self.assertAlmostEqual(math.sin(float(2*math.pi * tone*k/f)),
                                       math.sin(float(2*math.pi * signed*k/f)), delta=2e-12)

    def test_decimal_context_cannot_change_event_times(self):
        plan = ClockPlan(clock('4', points_hz=(Point('1/1', '12/1'),), interpolation='linear'), '1/1')
        expected = plan.events()
        with localcontext() as ctx:
            ctx.prec = 6
            ctx.rounding = 'ROUND_FLOOR'
            self.assertEqual(plan.events(), expected)

    def test_fractional_rates_do_not_round_to_integer_holds(self):
        a = ClockPlan(clock('15999.9999'), '1/1000').events()
        b = ClockPlan(clock('16000.0001'), '1/1000').events()
        self.assertNotEqual(a[1].time_s, b[1].time_s)
        self.assertLess(abs(a[1].time_s - b[1].time_s), 1e-12)
        self.assertNotEqual(a[1].time_s * 48000, round(a[1].time_s * 48000))


class NyquismicTimingState(unittest.TestCase):
    def test_half_open_chunks_exact_boundaries_and_absolute_ids(self):
        plan = ClockPlan(clock('8'), '1/1')
        chunks = ('0/1', '1/8', '3/16', '1/2', '7/8', '1/1')
        result = sum((plan.events(a, b) for a, b in zip(chunks, chunks[1:])), ())
        self.assertEqual(result, plan.events())
        self.assertEqual(plan.events('1/8', '1/8'), ())
        self.assertEqual(plan.events('1/8', '1/4')[0].index, 1)
        self.assertEqual(ClockPlan(clock('8'), '0/1').events(), ())

    def test_zero_and_nonzero_phase_first_capture(self):
        self.assertEqual(ClockPlan(clock('8'), '1/10').events()[0].time_s, 0)
        self.assertEqual(ClockPlan(clock('8', phase_cycles='1/4'), '1/10').events()[0].time_s, 3/32)
        self.assertEqual(ClockPlan(clock('8', phase_cycles='1/4'), '1/100').events(), ())

    def test_nonzero_origin_and_physical_time_queries(self):
        plan = ClockPlan(clock('8', origin_s='2/1'), '3/1')
        self.assertEqual(plan.events()[0].time_s, 2)
        self.assertEqual(plan.phase_at('5/2'), (0, Fraction(4)))
        with self.assertRaises(ContractError): plan.events('1/1')
        with self.assertRaises(ContractError): plan.phase_at('7/2')

    def test_coincident_reset_automation_and_capture_order(self):
        spec = clock('4', points_hz=(Point('1/2', '8/1'),), resets=(Reset('1/2'),))
        plan = ClockPlan(spec, '1/1')
        self.assertEqual([(e.epoch, e.crossing, e.time_s) for e in plan.events()],
                         [(0,0,0.), (0,1,.25), (1,0,.5), (1,1,.625), (1,2,.75), (1,3,.875)])
        self.assertEqual(plan.phase_at('1/2'), (1, Fraction(0)))
        self.assertEqual(plan.checkpoint('1/2').events_before, 2)

    def test_reset_at_excluded_end_is_checkpoint_state_not_extra_event(self):
        spec = clock('4', resets=(Reset('1/2'),))
        prefix = ClockPlan(spec, '1/2')
        complete = ClockPlan(spec, '1/1')
        checkpoint = prefix.checkpoint('1/2')
        self.assertEqual(checkpoint.epoch, 1)
        self.assertEqual(prefix.event_count, 2)
        self.assertEqual(complete.restore(checkpoint), complete.events('1/2'))

    def test_resets_near_capture_not_sorted_or_coalesced(self):
        before = ClockPlan(clock('4', resets=(Reset('499999999/1000000000'),)), '1/1')
        self.assertEqual(before.events()[2].epoch, 1)
        # Reset immediately AFTER an ordinary event would produce two captures
        # closer than the hard minimum spacing and must not be silently merged.
        with self.assertRaisesRegex(ContractError, 'spacing'):
            ClockPlan(clock('4', resets=(Reset('500000001/1000000000'),)), '1/1')

    def test_checkpoint_roundtrip_and_interior_region(self):
        spec = clock('4', points_hz=(Point('1/1', '12/1'),), interpolation='linear', resets=(Reset('1/2','1/4'),))
        plan = ClockPlan(spec, '1/1')
        for t in ('0/1', '1/3', '1/2', '7/8', '1/1'):
            checkpoint = plan.checkpoint(t)
            loaded = ClockCheckpoint.from_json(checkpoint.to_json())
            self.assertEqual(checkpoint, loaded)
            self.assertEqual(plan.restore(loaded), plan.events(t))
            self.assertEqual(checkpoint.events_before, len(plan.events(end_s=t)))
        with self.assertRaises(UnsupportedNyquismic): checkpoint.require_audio_restore()

    def test_checkpoint_tamper_foreign_seed_and_state_rejected(self):
        plan = ClockPlan(clock('8'), '1/1')
        cp = plan.checkpoint('1/2')
        for changed in (replace(cp, epoch=1), replace(cp, next_crossing=5), replace(cp, events_before=0),
                        replace(cp, clock_sha256='f'*64), replace(cp, phase_numerator_hex='5')):
            with self.subTest(changed=changed), self.assertRaises(ContractError): plan.restore(changed)
        foreign = replace(plan.spec, jitter=JitterSpec(seed='1'))
        with self.assertRaises(ContractError): ClockPlan(foreign, '1/1').restore(cp)
        for updates in ({'phase_denominator_hex':'0'}, {'phase_numerator_hex':'00'},
                        {'phase_numerator_hex':'x'}, {'events_before':True}, {'version':'2.0.0'}):
            with self.assertRaises(ContractError): replace(cp, **updates)

    def test_fractional_query_does_not_use_display_timestamp(self):
        plan = ClockPlan(clock('3'), '1/1')
        self.assertEqual([e.index for e in plan.events('1/3', '2/3')], [1])
        self.assertEqual([e.index for e in plan.events('333333334/1000000000', '2/3')], [])

    def test_sampler_clock_modulation_is_not_varispeed(self):
        original = sonic()
        fast_clock = replace(original, clock=clock('16'))
        self.assertEqual(source_time(original,'1/2'), source_time(fast_clock,'1/2'))
        for speed, expected in (('1/2',Fraction(1,4)), ('1/1',Fraction(1,2)), ('2/1',Fraction(1))):
            warp = replace(original, mode='playback_warp', playback=PlaybackMap(speed=speed))
            self.assertEqual(source_time(warp,'1/2'), expected)
            self.assertEqual(ClockPlan(warp.clock,'1/1').events(), ClockPlan(original.clock,'1/1').events())

    def test_playback_integral_and_explicit_boundary_rules(self):
        warp = replace(sonic(), mode='playback_warp',
                       playback=PlaybackMap(speed_points=(Point('1/1','3/1'),), interpolation='linear'))
        self.assertEqual(source_time(warp,'1/2'), Fraction(3,4))
        self.assertEqual(source_time(warp,'1/1'), Fraction(2))
        self.assertIsNone(source_time(warp,'1/1', bounded=True))
        hold = replace(warp, playback=replace(warp.playback,boundary='edge_hold'))
        self.assertEqual(source_time(hold,'1/1',bounded=True), 1)
        loop = replace(warp, playback=replace(warp.playback,boundary='loop',source_origin_s='1/4',loop_start_s='1/4',loop_end_s='3/4'))
        self.assertEqual(source_time(loop,'1/1',bounded=True), Fraction(1,4))
        self.assertEqual(source_time(loop,'0/1',bounded=True), Fraction(1,4))

    def test_sampler_boundary_requires_real_extent_and_handles_empty(self):
        spec=sonic()
        with self.assertRaises(ContractError): source_time(spec,'1/1',bounded=True)
        self.assertIsNone(source_time(spec,'1/1',bounded=True,input_extent_s='1/1'))
        self.assertEqual(source_time(replace(spec,input_boundary='edge_hold'),'1/1',bounded=True,input_extent_s='1/2'),Fraction(1,2))
        self.assertIsNone(source_time(replace(spec,input_boundary='edge_hold'),'0/1',bounded=True,input_extent_s='0/1'))
        with self.assertRaises(ContractError): source_time(spec,'1/1',input_extent_s='1/1')

    def test_playback_output_extent_stays_fixed(self):
        warp = replace(sonic(),mode='playback_warp',playback=PlaybackMap(speed='2/1'))
        self.assertEqual(bound(warp).end_s, '1/1')
        self.assertEqual(source_time(warp,'1/1'), 2)
        self.assertEqual(admit_foundation(warp,'1/1')[0].end_s, '1/1')

    def test_event_seed_is_absolute_counter_addressed(self):
        spec = sonic(channels=2)
        words = {k:event_seed(spec,epoch=0,crossing=k) for k in range(20)}
        self.assertEqual(words, {k:event_seed(spec,epoch=0,crossing=k) for k in reversed(range(20))})
        self.assertEqual(words, {k:event_seed(replace(spec,label='display'),epoch=0,crossing=k) for k in range(20)})
        self.assertEqual(event_seed(spec,epoch=0,crossing=1,channel=0), event_seed(spec,epoch=0,crossing=1,channel=1))
        independent=replace(spec,stereo_link='independent')
        self.assertNotEqual(event_seed(independent,epoch=0,crossing=1,channel=0), event_seed(independent,epoch=0,crossing=1,channel=1))
        self.assertNotEqual(words[0],event_seed(spec,epoch=1,crossing=0))
        self.assertNotEqual(words[0],event_seed(replace(spec,instance_id='duplicate'),epoch=0,crossing=0))

    def test_seed_and_cell_known_answers_from_independent_tagged_sha256(self):
        # Independently derived from the documented domain + sorted tagged JSON,
        # using only hashlib/json and integer arithmetic (no production imports).
        self.assertEqual(event_seed(sonic(),epoch=0,crossing=0),'14390279435749162811')
        self.assertEqual(clock_cell_value(sonic(),cell_index=0),Fraction('-9124178743656200821/18446744073709551616'))

    def test_link_groups_and_jitter_field_identity(self):
        spec = sonic(channels=2,clock_group='shared')
        duplicate = replace(spec,instance_id='other')
        self.assertEqual(event_seed(spec,epoch=0,crossing=0),event_seed(duplicate,epoch=0,crossing=0))
        for index in (0,1,200000):
            a = clock_cell_value(spec,cell_index=index)
            self.assertTrue(-1 < a < 1)
            self.assertEqual(a,clock_cell_value(duplicate,cell_index=index,channel=1))
        self.assertNotEqual(clock_cell_value(spec,cell_index=0),clock_cell_value(spec,cell_index=1))
        self.assertEqual(clock_cell_value(spec,cell_index=2), clock_cell_value(replace(spec,clock=replace(spec.clock,resets=(Reset('1/2'),))),cell_index=2))
        with self.assertRaises(ContractError): clock_cell_value(spec,cell_index=True)


class NyquismicContracts(unittest.TestCase):
    def test_roundtrip_every_record_and_defensive_serialization(self):
        route = ModulationRoute(points=(Point('1/1','1/2'),),depth=1)
        c = clock('8', routes=(route,), quantizer=RateQuantizer('nearest_hz',('4/1','8/1')),
                  jitter=JitterSpec('uniform_frequency_cells_v1',.1,seed='18446744073709551615'))
        specs = [SonicSpec(clock=c), replace(sonic(),mode='playback_warp',playback=PlaybackMap()),
                 SonicSpec(mode='cascade',clock=None,stages=tuple(sonic(instance_id=f'stage{i}') for i in range(3)))]
        values = [c.rate, RateReference(), c, route, c.jitter, c.quantizer, ResourceBudget(),
                  EvaluationPolicy(reference_rates_hz=(384000,768000)), bound(), *specs,
                  RackBoundary(sonic(),'1'*64,'2'*64,'spectral')]
        for value in values:
            with self.subTest(record=type(value).__name__):
                text = value.to_json()
                self.assertEqual(type(value).from_json(text), value)
                self.assertEqual(type(value).from_json(text).sha256,value.sha256)
        before = specs[0].sonic_sha256
        data = specs[0].to_dict();data['clock']['rate']['value']='16/1'
        self.assertEqual(specs[0].sonic_sha256,before)
        with self.assertRaises(FrozenInstanceError): specs[0].wet=0

    def test_rational_normalization_and_reference_binding(self):
        a=VirtualRate('1/3','ratio',RateReference('48000/1'))
        b=VirtualRate('2/6','ratio',RateReference('96000/2'))
        self.assertEqual(a,b)
        self.assertEqual(a.hz,16000)
        for evaluation_rate in (48000,192000,384000,768000):
            spec=SonicSpec(clock=ClockSpec(rate=a))
            identity=bound(spec,EvaluationPolicy(evaluation_rate_hz=evaluation_rate))
            self.assertEqual(spec.clock.rate.hz,16000)
            self.assertEqual(identity.sonic_sha256,spec.sonic_sha256)
        self.assertNotEqual(replace(a,reference=RateReference('44100/1')).sha256,a.sha256)
        with self.assertRaises(ContractError): VirtualRate('1/3','ratio')
        with self.assertRaises(ContractError): VirtualRate('8/1','Hz',RateReference())

    def test_resolved_reference_is_immutable_explicit_and_identity_bearing(self):
        ref=RateReference('440/1','resolved_control','pitch','a'*64)
        spec=SonicSpec(clock=ClockSpec(rate=VirtualRate('4/1','ratio',ref)))
        other=replace(spec,clock=replace(spec.clock,rate=replace(spec.clock.rate,reference=replace(ref,control_sha256='b'*64))))
        self.assertNotEqual(spec.sonic_sha256,other.sonic_sha256)
        with self.assertRaises(ContractError): RateReference(kind='resolved_control')
        with self.assertRaises(ContractError): RateReference(control_id='implicit')

    def test_frozen_default_sonic_and_evaluation_identities(self):
        self.assertEqual(SonicSpec().sonic_sha256,'08dcb6d3a9ddee94afba399d2a96a3f51e7252016031727af123953f6cb42921')
        self.assertEqual(SonicSpec().sha256,'b0ce639296a721e1fe33aab841b632d5a3dbc4acfdaf836f45cc1f4995f44f53')
        self.assertEqual(EvaluationPolicy().sha256,'c065ec529fd9a061ed5e77e64deb315c58d3e7d54d36b5f295d0a46a384ee044')

    def test_canonical_exact_numeric_serialization(self):
        a=replace(sonic(),wet=1)
        b=replace(sonic(),wet=1.0)
        self.assertEqual(a.canonical_bytes(),b.canonical_bytes())
        self.assertEqual(hashlib.sha256(a.canonical_bytes()).hexdigest(),a.sha256)
        self.assertEqual(replace(a,wet=-0.0).canonical_bytes(),replace(a,wet=0).canonical_bytes())

    def test_labels_are_only_cosmetic_field(self):
        base=sonic()
        named=replace(base,label='Clock I')
        self.assertEqual(base.sonic_sha256,named.sonic_sha256)
        self.assertNotEqual(base.sha256,named.sha256)
        self.assertEqual(bound(base).render_sha256,bound(named).render_sha256)
        cascade=SonicSpec(instance_id='cascade',mode='cascade',clock=None,stages=(base,))
        renamed=replace(cascade,label='Rack',stages=(named,))
        self.assertEqual(cascade.sonic_sha256,renamed.sonic_sha256)

    def test_each_sonic_control_mutation_changes_identity(self):
        s=sonic()
        variants=[replace(s,wet=.5),replace(s,bypass=True),replace(s,instance_id='second'),
                  replace(s,capture='nearest_left_tie_v1'),replace(s,reconstruction='linear_time_v1'),
                  replace(s,channels=2),replace(s,stereo_link='independent'),replace(s,clock_group='group'),
                  replace(s,band='sub'),replace(s,confine_delta=False),replace(s,input_boundary='edge_hold'),
                  replace(s,clock=clock('9')),replace(s,clock=replace(s.clock,origin_s='1/10')),
                  replace(s,clock=replace(s.clock,phase_cycles='1/4')),
                  replace(s,clock=replace(s.clock,resets=(Reset('1/2'),))),
                  replace(s,clock=replace(s.clock,points_hz=(Point('1/2','9/1'),))),
                  replace(s,clock=replace(s.clock,interpolation='linear')),
                  replace(s,clock=replace(s.clock,jitter=JitterSpec(seed='1'))),
                  replace(s,clock=replace(s.clock,jitter=JitterSpec(stream='other'))),
                  replace(s,clock=replace(s.clock,routes=(ModulationRoute(),))),
                  replace(s,clock=replace(s.clock,quantizer=RateQuantizer('nearest_hz',('4/1','8/1')))),
                  replace(s,mode='playback_warp',playback=PlaybackMap())]
        for other in variants:
            with self.subTest(other=other): self.assertNotEqual(s.sonic_sha256,other.sonic_sha256)

    def test_quality_context_and_revisions_change_render_not_sonic_identity(self):
        old=bound()
        variants=[replace(old,evaluation=EvaluationPolicy(evaluation_rate_hz=384000)),
                  replace(old,evaluation=EvaluationPolicy(reference_rates_hz=(384000,))),
                  replace(old,evaluation=EvaluationPolicy(budget=ResourceBudget(max_events=100))),
                  replace(old,delivery_rate_hz=44100), replace(old,start_s='1/4'),
                  replace(old,input_asset=Contract({**old.input_asset.to_dict(),'content_sha256':'f'*64})),replace(old,source_revision_sha256='f'*64),
                  replace(old,rack_revision_sha256='f'*64),replace(old,graph_revision_sha256='f'*64),
                  replace(old,context_sha256='f'*64)]
        for new in variants:
            self.assertEqual(new.sonic_sha256,old.sonic_sha256)
            self.assertNotEqual(new.render_sha256,old.render_sha256)
        self.assertEqual(RenderIdentity.from_json(old.to_json()).render_sha256,old.render_sha256)

    def test_input_rate_extent_channels_and_representation_are_identity_bearing(self):
        original=bound()
        for update in ({'sample_rate_hz':44100}, {'frame_count':24000}, {'level_domain':'pre_master'}):
            data=original.input_asset.to_dict(); data.update(update)
            updated=replace(original,input_asset=Contract(data))
            self.assertNotEqual(updated.render_sha256,original.render_sha256)
        with self.assertRaises(ContractError): replace(original,input_asset=asset(2))
        with self.assertRaises(ContractError): replace(original,input_asset=Contract(examples()['TimeMap']))
        with self.assertRaises(ContractError): bound(replace(sonic(),mode='playback_warp',playback=PlaybackMap(source_extent_s='2/1')))

    def test_order_is_not_commutative_and_reorder_preserves_random_instance(self):
        a,b=sonic(instance_id='a'),sonic('9',instance_id='b')
        left=SonicSpec(mode='cascade',clock=None,stages=(a,b))
        right=replace(left,stages=(b,a))
        self.assertNotEqual(left.sonic_sha256,right.sonic_sha256)
        self.assertEqual(event_seed(left.stages[0],epoch=0,crossing=4),event_seed(right.stages[1],epoch=0,crossing=4))
        c=clock('8',routes=(ModulationRoute('add','add_hz',1,initial='1/1'),ModulationRoute('multiply','log2_ratio',1,initial='1/1')))
        d=replace(c,routes=tuple(reversed(c.routes)))
        self.assertNotEqual(c.sha256,d.sha256)
        self.assertNotEqual(c.rate_bounds(),d.rate_bounds())

    def test_identity_declarations_do_not_authorize_placeholder_audio(self):
        values=[sonic(bypass=True),sonic(wet=0),SonicSpec(mode='cascade',clock=None,stages=())]
        for s in values:
            self.assertTrue(s.is_boundary_identity)
            with self.assertRaises(UnsupportedNyquismic): s.require_audio_execution()
        self.assertFalse(sonic().is_boundary_identity)
        self.assertFalse(replace(sonic(),clock=clock('8',routes=(ModulationRoute(depth=0),))).is_boundary_identity)
        for mode in ('sampler','playback_warp','cascade'):
            s=sonic() if mode=='sampler' else (replace(sonic(),mode=mode,playback=PlaybackMap()) if mode=='playback_warp' else SonicSpec(mode=mode,clock=None))
            with self.assertRaisesRegex(UnsupportedNyquismic,'unavailable'): s.require_audio_execution()

    def test_rack_and_registry_boundary_remain_closed(self):
        adapter=RackBoundary(sonic(),'1'*64,'2'*64,'bitcrush')
        with self.assertRaisesRegex(UnsupportedNyquismic,'#256'): adapter.require_execution()
        with self.assertRaises(ContractError): node_definition('core.nyquismic.v1')
        with self.assertRaises(ContractError): processor_definition('zg.nyquismic')
        with self.assertRaises(ContractError): Contract(sonic().to_dict())
        self.assertNotIn('nyquismic',str(schema('RenderRecipe',version='1.1.0')))

    def test_legacy_contract_factory_rack_bitcrush_and_aa_anchors_unchanged(self):
        from uptempo_harmony.synth import PRESETS
        from zaaggenz_dsp.bitcrush import BitcrushSpec
        from zaaggenz_dsp.antialias import filter_metadata
        payload=(FIXTURES/'nyquismic-legacy-anchors-v1.json').read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),LEGACY_SHA256)
        frozen=json.loads(payload)
        self.assertEqual(frozen['contract_examples'],{k:Contract(v).sha256 for k,v in examples().items()})
        self.assertEqual(frozen['schema_v1'],digest(schema()))
        self.assertEqual(frozen['factory_recipes'],{k:freeze_legacy(v.to_dict()).sha256 for k,v in PRESETS.items()})
        self.assertEqual(frozen['empty_racks'],{str(sr):empty_rack(freeze_legacy({'sr':sr})).sonic_sha256 for sr in (12000,48000)})
        self.assertEqual(frozen['bitcrush_default'],BitcrushSpec().to_dict())
        self.assertEqual(frozen['aa_filters'],{str(k):filter_metadata(k) for k in (1,2,4,8)})


class NyquismicInvalidAndBudgets(unittest.TestCase):
    def test_invalid_rate_values_not_coerced(self):
        for value in ('0/1','-1/1','1/0','1/-2','1/1000000001','9999999999999/1',
                      '1/1001','NaN','Inf',False,True,0,-1,float('nan'),float('inf'),None,[],{}):
            with self.subTest(value=value),self.assertRaises(ContractError): VirtualRate(value)
        self.assertEqual(VirtualRate('1/1000').hz,MIN_RATE_HZ)
        self.assertEqual(VirtualRate('1536000/1').hz,MAX_RATE_HZ)

    def test_nonfinite_bool_and_invalid_mix_seed_phase(self):
        for wet in (True,False,float('nan'),float('inf'),-0.1,1.1,'0',10**1000):
            with self.assertRaises(ContractError): sonic(wet=wet)
        for phase in ('1/1','-1/4','2/1'):
            with self.assertRaises(ContractError): clock(phase_cycles=phase)
            with self.assertRaises(ContractError): Reset('1/1',phase)
        for seed in ('-1','01','18446744073709551616',True,1):
            with self.assertRaises(ContractError): JitterSpec(seed=seed)
        with self.assertRaises(ContractError): sonic(channels=True)
        with self.assertRaises(ContractError): sonic(bypass=1)
        with self.assertRaises(ContractError): sonic(confine_delta=0)

    def test_unknown_or_unimplemented_policy_never_falls_back(self):
        for update in ({'version':'2.0.0'},{'mode':'varispeed'},{'prefilter':'sinc'},
                       {'reconstruction':'ideal_nonuniform_sinc'},{'tail':'infinite'},
                       {'capture':'cubic'},{'placement':'after_master'},{'bus':'SUB'},
                       {'band':'SUB'},{'reset_history':'reset_all'}):
            with self.assertRaises(ContractError): replace(sonic(),**update)
        with self.assertRaises(ContractError): clock(invalid_policy='clamp')
        with self.assertRaises(ContractError): clock(interpolation='cubic')
        with self.assertRaises(ContractError): ModulationRoute(mapping='multiply_hz')
        with self.assertRaises(ContractError): JitterSpec(model='gaussian_unbounded')
        with self.assertRaises(ContractError): RateQuantizer('nearest_hz',('4/1','8/1'),tie='random')
        with self.assertRaises(ContractError): EvaluationPolicy(audio_method='pretend_render')
        with self.assertRaises(ContractError): EvaluationPolicy(numerical_filter='unknown')

    def test_strict_json_missing_duplicate_unknown_and_type_errors(self):
        s=sonic()
        for modify in (lambda d:d.update(extra=1),lambda d:d.pop('tail'),lambda d:d.update(clock={}),
                       lambda d:d['clock'].update(automation={'unsupported':'sinusoid'}),
                       lambda d:d['clock'].update(routes={}),lambda d:d.update(stages={}),
                       lambda d:d.update(wet=float('nan'))):
            data=s.to_dict();modify(data)
            with self.assertRaises(ContractError): SonicSpec.from_dict(data)
        for text in ('{"version":"1","version":"2"}','NaN','Infinity','[]','{"wet":NaN}'):
            with self.assertRaises(ContractError): SonicSpec.from_json(text)
        with self.assertRaises(ContractError): SonicSpec.from_dict({'self':None})
        cyclic={};cyclic['self']=cyclic
        with self.assertRaises(ContractError): SonicSpec.from_dict(cyclic)
        with self.assertRaises(ContractError): sonic(label='\ud800')

    def test_complete_modulated_range_checked_even_bypassed(self):
        with self.assertRaisesRegex(ContractError,'complete modulated'):
            clock('8',routes=(ModulationRoute(depth=9,initial='-1/1'),))
        with self.assertRaises(ContractError): clock('8',points_hz=(Point('1/2','0/1'),))
        with self.assertRaises(ContractError): clock('1000000',routes=(ModulationRoute(mapping='log2_ratio',depth=2,initial='1/1'),))
        with self.assertRaises(ContractError): clock('1536000',jitter=JitterSpec('uniform_frequency_cells_v1',.1))
        c=clock('8',routes=(ModulationRoute(depth=1,initial='-1/1',points=(Point('1/1','1/1'),),interpolation='linear'),))
        self.assertEqual(c.rate_bounds(),(7,9))
        with self.assertRaises(UnsupportedNyquismic): admit_foundation(SonicSpec(clock=c,bypass=True),'1/1')

    def test_unsupported_geometry_routes_ladder_and_jitter_fail_even_zero_depth(self):
        for c in (clock(routes=(ModulationRoute(),)),clock(quantizer=RateQuantizer('nearest_hz',('8/1',))),
                  clock(jitter=JitterSpec('uniform_frequency_cells_v1',0))):
            with self.assertRaisesRegex(UnsupportedNyquismic,'#253'): ClockPlan(c,'1/1')

    def test_point_reset_and_route_counts_order_and_duplicates(self):
        for points in ((Point('0/1','8/1'),),(Point('1/2','8/1'),Point('1/2','9/1')),
                       (Point('3/4','8/1'),Point('1/2','9/1'))):
            with self.assertRaises(ContractError): clock(points_hz=points)
        with self.assertRaises(ContractError): clock(points_hz=[Point('1/1','8/1')])
        with self.assertRaises(ContractError): clock(points_hz=tuple(Point(f'{i+1}/1','8/1') for i in range(MAX_POINTS+1)))
        with self.assertRaises(ContractError): clock(resets=(Reset('0/1'),))
        with self.assertRaises(ContractError): clock(resets=(Reset('1/2'),Reset('1/2')))
        with self.assertRaises(ContractError): clock(resets=tuple(Reset(f'{i+1}/1') for i in range(MAX_RESETS+1)))
        with self.assertRaises(ContractError): clock(routes=(ModulationRoute(),ModulationRoute()))
        with self.assertRaises(ContractError): clock(routes=tuple(ModulationRoute(id=f'r{i}') for i in range(MAX_LANES+1)))
        with self.assertRaises(ContractError): RateQuantizer('nearest_hz',('8/1','4/1'))
        with self.assertRaises(ContractError): RateQuantizer('nearest_hz',('8/1','16/2'))
        with self.assertRaises(ContractError): RateQuantizer('none',('8/1',))

    def test_cascade_constraints_and_linked_clocks(self):
        a=sonic(instance_id='a')
        b=sonic(instance_id='b')
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(a,)*4)
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(a,a))
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(SonicSpec(mode='cascade',clock=None),))
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(a,replace(b,channels=2)))
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(a,replace(b,band='sub')))
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,capture='nearest_left_tie_v1')
        with self.assertRaises(ContractError): SonicSpec(mode='cascade',clock=None,stages=(replace(a,clock_group='g'),replace(b,clock_group='g',clock=clock('9'))))
        self.assertEqual(len(admit_foundation(SonicSpec(mode='cascade',clock=None,stages=(a,b)), '1/1')),2)

    def test_minimum_spacing_limit_admitted_and_nearby_reset_rejected(self):
        spec=clock('1536000',resets=(Reset('1/1536000'),))
        plan=ClockPlan(spec,'1/100000')
        events=plan.events()
        self.assertEqual(events[1].epoch,1)
        self.assertEqual(events[1].time_s,float(MIN_SPACING_S))
        with self.assertRaisesRegex(ContractError,'spacing'):
            ClockPlan(clock('1536000',resets=(Reset('1/2000000'),)),'1/100000')

    def test_affine_partition_additivity_and_checkpoint_property(self):
        spec=clock('7',points_hz=(Point('1/4','13/1'),Point('3/4','3/1')),interpolation='linear')
        plan=ClockPlan(spec,'1/1')
        cuts=('0/1','1/17','1/4','1/3','3/4','7/8','1/1')
        self.assertEqual(sum((plan.events(a,b) for a,b in zip(cuts,cuts[1:])),()),plan.events())
        for t in cuts:
            cp=plan.checkpoint(t)
            self.assertEqual(plan.events(end_s=t)+plan.restore(cp),plan.events())

    def test_event_admission_hard_and_user_budgets_preallocation(self):
        self.assertEqual(ClockPlan(clock('8'),'1/1',ResourceBudget(max_events=8)).event_count,8)
        with self.assertRaisesRegex(ContractError,'before event allocation'):
            ClockPlan(clock('8'),'1/1',ResourceBudget(max_events=7))
        with self.assertRaises(ContractError): ClockPlan(clock('1536000'),'1/1')
        with self.assertRaises(ContractError): ClockPlan(clock('8'),'3601/1')
        with self.assertRaises(ContractError): ClockPlan(clock('8',origin_s='1/1'),'0/1')
        with self.assertRaises(ContractError): ResourceBudget(max_events=MAX_EVENTS+1)
        with self.assertRaises(ContractError): ResourceBudget(max_events=True)
        with self.assertRaises(ContractError): ResourceBudget(max_filter_taps=MAX_FILTER_TAPS+1)

    def test_aggregate_stage_channel_and_node_admission(self):
        a,b=sonic(instance_id='a'),sonic(instance_id='b')
        cascade=SonicSpec(mode='cascade',clock=None,stages=(a,b))
        with self.assertRaisesRegex(ContractError,'aggregate'): admit_foundation(cascade,'1/1',ResourceBudget(max_events=15))
        with self.assertRaisesRegex(ContractError,'node budget'): admit_foundation(cascade,'1/1',ResourceBudget(max_nodes=2))
        stereo=sonic(channels=2,stereo_link='independent')
        with self.assertRaisesRegex(ContractError,'aggregate'): admit_foundation(stereo,'1/1',ResourceBudget(max_events=15))
        self.assertEqual(admit_foundation(replace(stereo,stereo_link='linked'),'1/1',ResourceBudget(max_events=8))[0].event_count,8)

    def test_frame_reference_pass_and_render_identity_admission(self):
        for rates in ((192000,), (384000,384000), (768000,384000), (4000000,), (True,), (384000,768000,1000000,2000000,3000000)):
            with self.assertRaises(ContractError): EvaluationPolicy(reference_rates_hz=rates)
        with self.assertRaises(ContractError): EvaluationPolicy(evaluation_rate_hz=True)
        with self.assertRaises(ContractError): EvaluationPolicy(evaluation_rate_hz=0)
        with self.assertRaises(ContractError): replace(bound(),end_s='3600/1')
        with self.assertRaises(ContractError): replace(bound(),start_s='2/1')
        with self.assertRaises(ContractError): replace(bound(),input_asset='foreign')
        with self.assertRaises(ContractError): bound(evaluation=EvaluationPolicy(budget=ResourceBudget(max_frames=100)))

    def test_read_bound_speed_loop_and_origin_validation(self):
        for speed in ('0/1','-1/1','65/1','1/65'):
            with self.assertRaises(ContractError): PlaybackMap(speed=speed)
        with self.assertRaises(ContractError): PlaybackMap(boundary='loop',loop_end_s='0/1')
        with self.assertRaises(ContractError): PlaybackMap(boundary='loop',loop_end_s='2/1')
        with self.assertRaises(ContractError): PlaybackMap(loop_crossfade_s='1/10')
        with self.assertRaises(ContractError): PlaybackMap(source_extent_s='0/1')
        with self.assertRaises(ContractError): SonicSpec(mode='playback_warp',clock=clock(origin_s='2/1'),playback=PlaybackMap(speed_points=(Point('1/1','2/1'),)))
        warp=replace(sonic(),mode='playback_warp',playback=PlaybackMap(speed='64/1'))
        with self.assertRaisesRegex(ContractError,'read extent'): source_time(warp,'3600/1')
        with self.assertRaisesRegex(ContractError,'read extent'): admit_foundation(warp,'1/1',ResourceBudget(max_read_s=63))
        with self.assertRaises(ContractError): source_time(SonicSpec(mode='cascade',clock=None),'1/1')
        tiny=replace(warp,playback=PlaybackMap(speed='2/1',boundary='loop',loop_end_s='1/1000000'))
        with self.assertRaisesRegex(ContractError,'loop traversal'): admit_foundation(tiny,'1/1')
        with self.assertRaises(ContractError): PlaybackMap(boundary='loop',loop_start_s='1/4')

    def test_cancellation_is_atomic_not_truncated_success(self):
        plan=ClockPlan(clock('1000'),'1/1')
        with self.assertRaises(ClockCancelled): plan.events(cancelled=lambda:True)
        calls=[]
        def cancel():
            calls.append(1)
            return len(calls)>2
        with self.assertRaises(ClockCancelled): plan.events(cancelled=cancel)
        self.assertEqual(len(plan.events()),1000)
        with self.assertRaises(ContractError): plan.events(cancelled=True)


if __name__ == '__main__':
    unittest.main()
