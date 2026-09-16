from __future__ import annotations
import numpy as np
from zaaggenz_components import ComponentAnalysis
from zaaggenz_jobs import JobClass,JobError
from zaaggenz_jobs.memory import authoritative_memory_reservation
from .engine import retune_components
from .model import SpectralRetuneRequest,estimate_retune_target_bytes


def estimate_retune_memory_bytes(analysis,request=None):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    if request is not None and not isinstance(request,SpectralRetuneRequest):raise JobError('SpectralRetuneRequest required')
    arrays=(analysis.source,analysis.sinusoidal,analysis.transient,analysis.residual,analysis.transient_mask)
    resident=sum(np.asarray(a).nbytes for a in arrays)
    target_bytes=estimate_retune_target_bytes(request) if request is not None else 0
    # Accepted conservative model: retained analysis plus reconstruction/result
    # copies, structured component-plan overhead, and the entire pre-filter target
    # candidate budget.  This is an admission estimate, not an OS RSS claim.
    return max(1,int(resident*6+target_bytes+2*1024*1024))


def make_retune_executor(analysis,request):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    if not isinstance(request,SpectralRetuneRequest):raise JobError('SpectralRetuneRequest required')
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.01)
        return retune_components(analysis,request,checkpoint=ctx.check_cancelled,progress=lambda p:ctx.progress(max(.01,float(p))))
    return execute


def submit_retune_job(scheduler,revision_id,analysis,request,*,estimated_memory_bytes=None):
    minimum=estimate_retune_memory_bytes(analysis,request)
    estimate=authoritative_memory_reservation(minimum,estimated_memory_bytes)
    return scheduler.submit(JobClass.RENDER,revision_id,make_retune_executor(analysis,request),estimated_memory_bytes=estimate)
