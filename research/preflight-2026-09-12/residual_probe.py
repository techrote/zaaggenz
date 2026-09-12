"""Why exact residual reconstruction does not validate spectral transformation.
All sinusoids and imperfect estimates below are deliberately constructed.
"""
from __future__ import annotations
import numpy as np
from common import METHOD, rms, db, dump, table


def run(out):
    rows=[]; sr=48000
    for duration in (.5,1.,4.):
        t=np.arange(round(sr*duration))/sr
        source=np.sin(2*np.pi*440*t+.17)
        target=np.sin(2*np.pi*660*t+.17)
        for offset in (0.,.05,.5,2.):
            for amplitude in (.95,1.,1.05):
                estimated=amplitude*np.sin(2*np.pi*(440+offset)*t+.17)
                residual=source-estimated
                recovered=estimated+residual
                # Same flawed component, moved to target, plus unchanged residual.
                transformed=amplitude*target+residual
                rows.append(dict(duration_s=duration,frequency_error_hz=offset,
                    estimated_amplitude=amplitude,
                    identity_error_db=db(rms(recovered-source)/rms(source)),
                    residual_relative_rms=db(rms(residual)/rms(source)),
                    transformed_error_db=db(rms(transformed-target)/rms(target))))
    table(out/'residual_counterexample.csv',rows)
    dump(out/'residual_interpretation.json',{
       'method':METHOD,'source_hz':440,'target_hz':660,'sr':sr,'cases':len(rows),
       'status':'controlled counterexample, not a partial tracker',
       'finding':'Exact x = estimated + residual does not prove the estimate is transformable. Frozen residual can retain the original sinusoid and a negative copy of the inaccurate estimate.',
       'required_tests':['identity bypass','analysis/resynthesis fidelity','known-target transformation fidelity','source/target ghost energy','duration and phase-error sensitivity'],
       'policy':'Do not discard all residual; do not call algebraic identity evidence of clean retuning. Use confidence-aware transform budgets and component/residual ownership.'})
    return rows
