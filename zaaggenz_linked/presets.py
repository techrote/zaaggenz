"""Synthetic linked-return fixture; compositional mechanics, not preference claims."""
from zaaggenz_harmony import SonoritySpec,SonorityTone
from zaaggenz_meter import MeterPlan
from zaaggenz_meter.model import VERSION as METER_VERSION
from .model import LinkedEventPlan,VERSION

def _meter():
    windows=[{'start_beat':'0/1','end_beat':'16/1','reset_on_entry':True}]
    clocks=[
      {'id':'articulation','kind':'nested','period_beats':'1/2','phase_beats':'0/1','relation':None,'active_windows':windows,'reset_beats':[]},
      {'id':'bounce','kind':'nested','period_beats':'1/1','phase_beats':'0/1','relation':{'reference_id':'articulation','period_numerator':2,'period_denominator':1},'active_windows':windows,'reset_beats':[]},
      {'id':'sway','kind':'nested','period_beats':'2/1','phase_beats':'0/1','relation':{'reference_id':'bounce','period_numerator':2,'period_denominator':1},'active_windows':windows,'reset_beats':[]},
    ]
    return MeterPlan({'format':'zaaggenz-meter-plan','version':METER_VERSION,'id':'linked-return-124','description':'Sixteen-beat exact nested articulation/bounce/sway hierarchy retained through local violation and return.','end_beat':'16/1','stable_clock_id':'sway','clocks':clocks,'bindings':[{'id':'sway-anchor','clock_id':'sway','layer':'body','control':'accent_db','values':[-3.0],'stability':'anchor'}]})

def linked_fakeout_return():
    son=SonoritySpec('return-home',0,(SonorityTone('root',degree_offset=0),SonorityTone('third',degree_offset=4),SonorityTone('fifth',degree_offset=7)),bass_tone_id='root',context_id='linked-return').to_dict()
    return LinkedEventPlan({
      'format':'zaaggenz-linked-return','version':VERSION,'id':'synthetic-linked-fakeout-return',
      'description':'Four-phase source-preserving double event: established local expectation, substitute violation, optional linked reinterpretation bridge, and shared harmonic return.',
      'end_beat':'16/1','source_family':'locked-bloom',
      'phases':[
       {'name':'preparation','start_beat':'0/1','end_beat':'8/1','role':'establish','layers':['synthline','body']},
       {'name':'violation','start_beat':'8/1','end_beat':'10/1','role':'fakeout','layers':['synthline']},
       {'name':'bridge','start_beat':'10/1','end_beat':'15/1','role':'transition','layers':['synthline','aux']},
       {'name':'return','start_beat':'15/1','end_beat':'16/1','role':'return','layers':['synthline','body','sub']},
      ],
      'preparation':{'step_beats':'2/1','degrees':[0,2,4,7],'duration_beats':'1/1','gain_db':-18.0},
      'local_expectation':{'beat':'8/1','duration_beats':'1/1','expected_degree':7,'substitute_degree':9,'detune_cents':0.0,'gain_db':-18.0},
      'bridge':{'step_beats':'1/1','duration_beats':'1/2','gain_db':-18.0,'neutral_degree_offsets':[0,-3,0,-3,0],'unrelated_degree_offsets':[4,-2,5,-4,3]},
      'return_destination':{'beat':'15/1','duration_beats':'1/1','degree':0,'detune_cents':0.0,'gain_db':-18.0},
      'return_sonority':son,'meter_plan':_meter().to_dict(),'stable_clock_id':'sway',
      'transforms':[
       {'kind':'withheld-low-band-arrival','phase':'violation','layer':'sub','apply_policy':'deferred-explicit'},
       {'kind':'motif-completion','phase':'bridge','layer':'synthline','apply_policy':'applied-source-derived'},
       {'kind':'spectral-emergence','phase':'bridge','layer':'aux','apply_policy':'deferred-explicit'},
       {'kind':'envelope-morph','phase':'bridge','layer':'synthline','apply_policy':'deferred-explicit'},
       {'kind':'restore-phase-alignment','phase':'bridge','layer':'body','apply_policy':'deferred-explicit'},
      ],
      'engine_model':{'local_prediction_probability':0.85,'destination_probability':0.9,'uncertainty':0.2,'semantics':'generator-state-not-listener-outcome'}
    })
