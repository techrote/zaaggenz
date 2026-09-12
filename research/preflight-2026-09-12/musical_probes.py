"""Executable musical representation fixtures, not frozen zaaggenz schemas."""
from __future__ import annotations
from dataclasses import dataclass
from fractions import Fraction
import math
import numpy as np
from common import METHOD, SEED, dump, table, cents


@dataclass(frozen=True)
class Scale:
    description: str
    ratios: tuple[float,...]  # explicit entries include period; 1/1 implicit
    def degree(self,k):
        if not self.ratios or self.ratios[-1]<=0:
            raise ValueError('empty/unplayable scale')
        periods,index=divmod(int(k),len(self.ratios))
        value=self.ratios[-1]**periods*(1.0 if index==0 else self.ratios[index-1])
        if not math.isfinite(value) or value<=0: raise ValueError('frequency overflow')
        return value


def parse_scl(text, max_notes=4096):
    if len(text)>1024*1024: raise ValueError('scale text too large')
    # Preserve a blank description; comments, not all blank lines, are removed.
    lines=[s.strip() for s in text.splitlines() if not s.lstrip().startswith('!')]
    if len(lines)<2: raise ValueError('description and count required')
    desc=lines[0]
    try: n=int(lines[1])
    except ValueError as e: raise ValueError('invalid note count') from e
    if not 0<=n<=max_notes: raise ValueError('note count out of bounds')
    vals=[]
    for line in lines[2:]:
        if not line: continue
        token=line.split()[0]
        if len(vals)==n: raise ValueError('unexpected extra pitch line')
        try:
            ratio=2**(float(token)/1200) if '.' in token else float(Fraction(token))
        except (ValueError,ZeroDivisionError,OverflowError) as e:
            raise ValueError('invalid pitch') from e
        if not math.isfinite(ratio) or ratio<=0: raise ValueError('invalid positive ratio')
        vals.append(ratio)
    if len(vals)!=n: raise ValueError('wrong pitch count')
    return Scale(desc,tuple(vals))


@dataclass(frozen=True)
class Mapping:
    size:int; first:int; last:int; middle:int; reference:int; hz:float
    formal:int; degrees:tuple[int|None,...]
    def degree(self,key):
        if self.size==0: return key-self.middle
        q,r=divmod(key-self.middle,self.size)
        d=self.degrees[r]
        return None if d is None else q*self.formal+d
    def frequency(self,scale,key):
        if not self.first<=key<=self.last: return None
        d,r=self.degree(key),self.degree(self.reference)
        if r is None: raise ValueError('unmapped reference note')
        if d is None: return None
        f=self.hz*scale.degree(d)/scale.degree(r)
        if not math.isfinite(f) or f<=0: raise ValueError('unplayable frequency')
        return f


def parse_kbm(text,max_keys=128):
    lines=[s.split('!',1)[0].strip() for s in text.splitlines()]
    lines=[s for s in lines if s]
    if len(lines)<7: raise ValueError('seven header fields required')
    try:
        size,first,last,middle,reference=map(int,lines[:5])
        hz=float(lines[5]); formal=int(lines[6])
        if not 0<=size<=max_keys or not 0<=first<=last<=127 or not 0<=middle<=127 or not 0<=reference<=127:
            raise ValueError('invalid mapping header')
        if not math.isfinite(hz) or hz<=0: raise ValueError('invalid reference Hz')
        entries=[None if s.lower()=='x' else int(s) for s in lines[7:]]
        if len(entries)>size: raise ValueError('too many entries')
        entries += [None]*(size-len(entries))
    except (ValueError,OverflowError) as e: raise ValueError('invalid keyboard map') from e
    result=Mapping(size,first,last,middle,reference,hz,formal,tuple(entries))
    if result.degree(reference) is None: raise ValueError('reference note unmapped')
    return result


def sample_at(beat,bpm,sr):
    """Round ONCE at absolute position using exact rational beat/tempo."""
    if isinstance(sr, bool) or int(sr) != sr or sr <= 0:
        raise ValueError('positive integral sample rate required')
    tempo = Fraction(str(bpm))
    if tempo <= 0: raise ValueError('positive tempo required')
    return round(Fraction(beat)*60*int(sr)/tempo)


def run_tunings(out):
    rows=[]
    for name,n,period in [('12edo',12,2),('19edo',19,2),('31edo',31,2),('13ed3',13,3)]:
        text=name+'\n'+str(n)+'\n'+'\n'.join(f'{1200*math.log2(period)*k/n:.12f}' for k in range(1,n+1))+'\n'
        scale=parse_scl(text)
        for k in (-n,-1,0,1,n,n+1):
            rows.append(dict(scale=name,degree=k,ratio=scale.degree(k),expected=period**(k/n),
                             error_cents=float(cents(scale.degree(k)/(period**(k/n))))))
    et=parse_scl('12edo\n12\n'+'\n'.join(f'{100*k}.0' for k in range(1,13)))
    kbm=parse_kbm('12\n0\n127\n60\n69\n440.0\n12\n'+'\n'.join(str(k) for k in range(12)))
    mapping={str(k):kbm.frequency(et,k) for k in (0,60,68,69,70,127)}
    sparse=parse_kbm('3\n0\n127\n60\n60\n48.0\n7\n0\nx\n4')
    sparse_freq={str(k):sparse.frequency(et,k) for k in range(57,66)}
    dump(out/'tuning.json',{'method':METHOD,'rows':rows,'12edo_mapping_hz':mapping,'sparse_mapping_hz':sparse_freq,
        'integer_1200_ratio':parse_scl('integer\n1\n1200').degree(1),
        'decimal_1200_ratio':parse_scl('cents\n1\n1200.0').degree(1),
        'scope':'SCL/KBM subset test oracle; validate/import separately; not production contract freeze'})
    return rows


def run_clocks(out):
    rows=[]
    for sr in (44100,48000,96000):
        for bpm in (20,137,199.7,240,360):
            for subdivision in (1,2,4,8,12):
                steps=256*subdivision
                duration=Fraction(256)*60*sr/Fraction(str(bpm))
                naive=steps*sample_at(Fraction(1,subdivision),bpm,sr)
                exact=sample_at(Fraction(256),bpm,sr)
                rows.append(dict(sr=sr,bpm=bpm,subdivision=subdivision,bars=64,
                    rounding_once_error_samples=float(exact-duration),
                    repeated_rounded_step_error_samples=float(naive-duration),
                    repeated_error_ms=float((naive-duration)*1000/sr)))
    table(out/'clock_drift.csv',rows)
    return rows


def run_phrases(out):
    rng=np.random.default_rng(SEED+3); rows=[]
    # At each of four phrase positions, hold one stable role distribution.
    # This is GENERATOR entropy, not a measured listener expectation.
    for mode in ('stable_fill_location','scattered_fill_location'):
        positions=[]; identities=[]
        for trial in range(96):
            position=3 if mode=='stable_fill_location' else int(rng.integers(0,4))
            identity=int(rng.integers(0,8)); positions.append(position);identities.append(identity)
            rows.append(dict(condition=mode,trial=trial,variation_bar=position+1,
                             fill_id=identity,return_beat=16,source_inventory='fixed-8-gesture-set'))
    table(out/'phrase_inventory.csv',rows)
    summaries={}
    for mode in ('stable_fill_location','scattered_fill_location'):
        p=np.bincount([r['variation_bar']-1 for r in rows if r['condition']==mode],minlength=4)/96
        summaries[mode]={'empirical_location_entropy_bits':float(-sum(p[p>0]*np.log2(p[p>0]))),
                         'designed_fill_entropy_bits':3.,'return_beat':16}
    # Compact symbolic manipulation matrix for future renderer; no participant data.
    factorial=[]
    for violation in (0,1):
        for recovery in (0,1):
            factorial.append({'id':f'V{violation}R{recovery}','violation':bool(violation),'recovery':bool(recovery),
                'probe_beat':16,'return_beat':18,'duration_beats':24,
                'shared_source_id':'synthetic-placeholder-NOT-locked-bloom',
                'status':'symbolic design only; audio matching/manipulation checks pending'})
    dump(out/'phrase_design.json',{'method':METHOD,'summary':summaries,'factorial':factorial,
         'contrast':'R11 - R10 - R01 + R00',
         'caution':'Expected role != exact event prediction. No reward/biochemistry inferred.'})
    return summaries


def main(out):
    return {'tuning_rows':len(run_tunings(out)),'clock_rows':len(run_clocks(out)),'phrase':run_phrases(out)}
