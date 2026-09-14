from __future__ import annotations
import numpy as np
from zaaggenz_jobs import JobClass,JobError
from .engine import retune_components
from .model import SpectralRetuneRequest

def estimate_retune_memory_bytes(analysis):
    arrays=(analysis.source,analysis.sinusoidal,analysis.transient,analysis.residual,analysis.transient_mask)
    raw=sum(np.asarray(a).nbytes for a in arrays)
    return max(1,min(256*1024*1024,int(raw*6+2*1024*1024)))

def make_retune_executor(analysis,request):
    if not isinstance(request,SpectralRetuneRequest):raise JobError('SpectralRetuneRequest required')
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.01)
        return retune_components(analysis,request,checkpoint=ctx.check_cancelled,progress=lambda p:ctx.progress(max(.01,float(p))))
    return execute

def submit_retune_job(scheduler,revision_id,analysis,request,*,estimated_memory_bytes=None):
    estimate=estimate_retune_memory_bytes(analysis) if estimated_memory_bytes is None else estimated_memory_bytes
    return scheduler.submit(JobClass.RENDER,revision_id,make_retune_executor(analysis,request),estimated_memory_bytes=estimate)
