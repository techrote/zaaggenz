from __future__ import annotations
from .core import Tuning,KeyboardMap

def _linear(count,middle=60,reference=60):return KeyboardMap(0,127,middle,reference,count,tuple(range(count)))

def fixture_pack():
    """Small synthetic/reference-math set; not a cultural mode library or quality ranking."""
    tet12=tuple(2**(k/12) for k in range(12))
    ratio=(1.,9/8,5/4,4/3,3/2,5/3,15/8)
    tritave=tuple(3**(k/13) for k in range(13))
    return {
      '12tet-a440':Tuning('12tet-a440',440.,0,2.,tet12,_linear(12,69,69),'12 equal divisions of 2:1','mathematical reference'),
      'synthetic-ratio-7':Tuning('synthetic-ratio-7',48.,0,2.,ratio,_linear(7),'Synthetic 7-degree ratio fixture','synthetic test fixture'),
      'synthetic-13ed3':Tuning('synthetic-13ed3',48.,0,3.,tritave,_linear(13),'13 equal divisions of a 3:1 period','synthetic non-octave fixture'),
    }
