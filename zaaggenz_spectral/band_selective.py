from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import math
import numpy as np
from zaaggenz_components import analyse_components
from zaaggenz_dsp import (BAND_NAMES,BitcrushSpec,CompressionSpec,band_filter_metadata,bitcrush,compress,
                          route_band_processors)
from .engine import retune_components
from .model import SpectralRetuneRequest
from .chordness_engine import apply_chordness
from .chordness_request import ChordnessRequest

class BandSelectiveError(ValueError):pass
STAGES=('spectral','gain','compression','bitcrush')

@dataclass(frozen=True)
class BandSlotSpec:
    gain_db:float=0.
    compression:CompressionSpec|None=None
    bitcrush:BitcrushSpec|None=None
    spectral:SpectralRetuneRequest|ChordnessRequest|None=None
    stage_order:tuple[str,...]=STAGES
    def __post_init__(self):
        gain=float(self.gain_db)
        if not math.isfinite(gain) or not -36<=gain<=24:raise BandSelectiveError('gain_db must be in [-36,24]')
        if self.compression is not None and not isinstance(self.compression,CompressionSpec):raise BandSelectiveError('CompressionSpec required')
        if self.bitcrush is not None and not isinstance(self.bitcrush,BitcrushSpec):raise BandSelectiveError('BitcrushSpec required')
        if self.spectral is not None and not isinstance(self.spectral,(SpectralRetuneRequest,ChordnessRequest)):raise BandSelectiveError('spectral slot requires SpectralRetuneRequest or ChordnessRequest')
        order=tuple(self.stage_order)
        if len(order)!=4 or len(set(order))!=4 or set(order)!=set(STAGES):raise BandSelectiveError('stage_order must contain spectral, gain, compression, bitcrush exactly once')
        object.__setattr__(self,'gain_db',gain);object.__setattr__(self,'stage_order',order)
    @property
    def identity(self):
        comp=self.compression is None or self.compression.wet==0 or (self.compression.ratio==1 and self.compression.makeup_db==0)
        crush=self.bitcrush is None or self.bitcrush.wet==0
        spectral=self.spectral is None or (isinstance(self.spectral,SpectralRetuneRequest) and self.spectral.amount==0) or (isinstance(self.spectral,ChordnessRequest) and self.spectral.mode=='off')
        return self.gain_db==0 and comp and crush and spectral
    def to_dict(self):
        spectral=None if self.spectral is None else self.spectral.to_dict()
        return {'gain_db':self.gain_db,'compression':None if self.compression is None else self.compression.to_dict(),
                'bitcrush':None if self.bitcrush is None else self.bitcrush.to_dict(),'spectral':spectral,
                'stage_order':list(self.stage_order),'identity':self.identity,'declared_latency_samples':0}

@dataclass(frozen=True)
class BandSelectiveRequest:
    crossovers_hz:tuple[float,float,float]=(105.,520.,3600.)
    slots:tuple[BandSlotSpec|None,...]=(None,None,None,None)
    confine_delta:tuple[bool,bool,bool,bool]=(True,True,True,True)
    def __post_init__(self):
        slots=tuple(self.slots);confine=tuple(self.confine_delta)
        if len(slots)!=4 or any(x is not None and not isinstance(x,BandSlotSpec) for x in slots):raise BandSelectiveError('four band slots required')
        if len(confine)!=4 or any(type(x)is not bool for x in confine):raise BandSelectiveError('four boolean confine flags required')
        c=tuple(float(x) for x in self.crossovers_hz)
        if len(c)!=3 or any(not math.isfinite(x) for x in c) or not 20<=c[0]<c[1]<c[2]:raise BandSelectiveError('invalid crossovers')
        object.__setattr__(self,'slots',slots);object.__setattr__(self,'confine_delta',confine);object.__setattr__(self,'crossovers_hz',c)
    def to_dict(self,sample_rate_hz=None):
        filter_info=None if sample_rate_hz is None else band_filter_metadata(self.crossovers_hz,sample_rate_hz)
        return {'kind':'BandSelectiveDSPRequest','version':'1.0.0','bands':list(BAND_NAMES),'crossovers_hz':list(self.crossovers_hz),
                'slots':[None if x is None else x.to_dict() for x in self.slots],'confine_delta':list(self.confine_delta),
                'filter':filter_info,'output_policy':{'normalization':'none','master_gain_db':0.,'declared_latency_samples':0},
                'spill_policy':'confine_delta=false deliberately permits raw effect delta outside the selected crossover pocket'}

@dataclass(frozen=True)
class BandSelectiveResult:
    request:BandSelectiveRequest
    source:np.ndarray
    audio:np.ndarray
    band_reports:tuple
    slot_reports:tuple[dict|None,...]
    sample_rate_hz:int
    def __post_init__(self):
        source=np.asarray(self.source);audio=np.asarray(self.audio)
        if source.shape!=audio.shape or not np.isfinite(audio).all():raise BandSelectiveError('invalid output')
        object.__setattr__(self,'slot_reports',tuple(deepcopy(self.slot_reports)))
    @property
    def diagnostics(self):
        return {'identity_path':bool(np.array_equal(self.source,self.audio)),'filter':band_filter_metadata(self.request.crossovers_hz,self.sample_rate_hz),
                'bands':[x.to_dict() for x in self.band_reports],'slots':deepcopy(list(self.slot_reports)),'normalization':'none','master_gain_db':0.,'declared_latency_samples':0}
    @property
    def inspection(self):return {'request':self.request.to_dict(self.sample_rate_hz),'diagnostics':self.diagnostics}

def _process_slot(audio,sample_rate_hz,slot):
    source=np.asarray(audio)
    if slot.identity:return source.copy(),{'identity_path':True,'stage_order':list(slot.stage_order),'stages':[]}
    current=np.asarray(source,dtype=np.float64);rows=[]
    for stage in slot.stage_order:
        if stage=='gain':
            if slot.gain_db!=0:
                current=current*10.**(slot.gain_db/20.);rows.append({'stage':'gain','gain_db':slot.gain_db,'declared_latency_samples':0})
        elif stage=='compression':
            if slot.compression is not None:
                result=compress(current,sample_rate_hz,slot.compression);current=np.asarray(result.audio,dtype=np.float64)
                rows.append({'stage':'compression','spec':slot.compression.to_dict(),'diagnostics':result.diagnostics})
        elif stage=='bitcrush':
            if slot.bitcrush is not None:
                result=bitcrush(current,slot.bitcrush);current=np.asarray(result.audio,dtype=np.float64)
                rows.append({'stage':'bitcrush','spec':slot.bitcrush.to_dict(),'diagnostics':result.diagnostics,
                             'alias_policy':'intentional unfiltered quantization/sample-hold images; crossover delta confinement is the spill control'})
        elif stage=='spectral':
            if slot.spectral is not None:
                analysis=analyse_components(np.asarray(current,dtype=np.float32),sample_rate_hz)
                if isinstance(slot.spectral,SpectralRetuneRequest):result=retune_components(analysis,slot.spectral)
                else:result=apply_chordness(analysis,slot.spectral)
                current=np.asarray(result.audio,dtype=np.float64);rows.append({'stage':'spectral','request':slot.spectral.to_dict(),'diagnostics':deepcopy(result.diagnostics)})
        else:raise BandSelectiveError('unknown stage')
    return current,{'identity_path':bool(np.array_equal(source,current)),'stage_order':list(slot.stage_order),'stages':rows}

def process_band_selective(source,sample_rate_hz,request):
    if not isinstance(request,BandSelectiveRequest):raise BandSelectiveError('BandSelectiveRequest required')
    if type(sample_rate_hz)is not int or not 8000<=sample_rate_hz<=192000:raise BandSelectiveError('sample rate out of range')
    band_filter_metadata(request.crossovers_hz,sample_rate_hz)
    src=np.asarray(source)
    if src.ndim not in (1,2) or not np.issubdtype(src.dtype,np.number) or not np.isfinite(src).all():raise BandSelectiveError('finite mono/stereo source required')
    if all(slot is None or slot.identity for slot in request.slots):
        reports=[]
        from zaaggenz_dsp.band_router import BandDeltaReport
        for i,name in enumerate(BAND_NAMES):reports.append(BandDeltaReport(name,request.slots[i] is not None,bool(request.confine_delta[i]),0.,0.,0.,(0.,0.,0.,0.)))
        return BandSelectiveResult(request,src.copy(),src.copy(),tuple(reports),tuple(None if x is None else {'identity_path':True,'stage_order':list(x.stage_order),'stages':[]} for x in request.slots),sample_rate_hz)
    captured=[None,None,None,None];processors=[]
    for i,slot in enumerate(request.slots):
        if slot is None:processors.append(None);continue
        def make(index,spec):
            def processor(band):
                audio,report=_process_slot(band,sample_rate_hz,spec);captured[index]=report;return audio
            return processor
        processors.append(make(i,slot))
    audio,reports=route_band_processors(src,sample_rate_hz,request.crossovers_hz,tuple(processors),request.confine_delta)
    return BandSelectiveResult(request,src.copy(),np.asarray(audio),reports,tuple(captured),sample_rate_hz)
