from __future__ import annotations
import numpy as np
from zaaggenz_components import ComponentAnalysis
from zaaggenz_jobs import JobClass,JobError
from .chordness_engine import apply_chordness
from .chordness_request import ChordnessRequest

def estimate_chordness_memory_bytes(analysis):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    arrays=(analysis.source,analysis.sinusoidal,analysis.transient,analysis.residual,analysis.transient_mask)
    return max(1,int(sum(np.asarray(x).nbytes for x in arrays)*7+3*1024*1024))

def make_chordness_executor(analysis,request):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    if not isinstance(request,ChordnessRequest):raise JobError('ChordnessRequest required')
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.01)
        return apply_chordness(analysis,request,checkpoint=ctx.check_cancelled,progress=lambda p:ctx.progress(max(.01,float(p))))
    return execute

def submit_chordness_job(scheduler,revision_id,analysis,request,*,estimated_memory_bytes=None):
    estimate=estimate_chordness_memory_bytes(analysis) if estimated_memory_bytes is None else estimated_memory_bytes
    return scheduler.submit(JobClass.RENDER,revision_id,make_chordness_executor(analysis,request),estimated_memory_bytes=estimate)
