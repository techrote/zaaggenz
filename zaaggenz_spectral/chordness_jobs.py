from __future__ import annotations
import numpy as np
from zaaggenz_components import ComponentAnalysis
from zaaggenz_jobs import JobClass,JobError
from zaaggenz_jobs.memory import authoritative_memory_reservation
from .chordness_engine import apply_chordness
from .chordness_request import ChordnessRequest


def estimate_chordness_memory_bytes(analysis):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    arrays=(analysis.source,analysis.sinusoidal,analysis.transient,analysis.residual,analysis.transient_mask)
    resident=sum(np.asarray(x).nbytes for x in arrays)
    # Accepted conservative model: retained analysis plus transformed bundle,
    # descriptor/reconstruction/result working sets and a fixed metadata margin.
    # This is admission accounting, not a claim about exact process RSS.
    return max(1,int(resident*7+3*1024*1024))


def make_chordness_executor(analysis,request):
    if not isinstance(analysis,ComponentAnalysis):raise JobError('ComponentAnalysis required')
    if not isinstance(request,ChordnessRequest):raise JobError('ChordnessRequest required')
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.01)
        return apply_chordness(analysis,request,checkpoint=ctx.check_cancelled,progress=lambda p:ctx.progress(max(.01,float(p))))
    return execute


def submit_chordness_job(scheduler,revision_id,analysis,request,*,estimated_memory_bytes=None):
    minimum=estimate_chordness_memory_bytes(analysis)
    estimate=authoritative_memory_reservation(minimum,estimated_memory_bytes)
    return scheduler.submit(JobClass.RENDER,revision_id,make_chordness_executor(analysis,request),estimated_memory_bytes=estimate)
