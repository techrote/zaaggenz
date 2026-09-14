from __future__ import annotations
from zaaggenz_jobs import JobClass,JobError
from .adaptive_engine import propose_adaptive_tuning
from .adaptive_model import AdaptiveState,AdaptiveTuningRequest
from .dissonance_curve import sensitivity_candidates
from .dissonance_model import DissonanceModelSpec,IntervalGrid,TimbreSpectrum

def make_dissonance_map_executor(a,b,grid=None,model=None):
    if not isinstance(a,TimbreSpectrum) or not isinstance(b,TimbreSpectrum):raise JobError('two TimbreSpectrum values required')
    grid=grid or IntervalGrid();model=model or DissonanceModelSpec()
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.05);result=sensitivity_candidates(a,b,grid,model);ctx.check_cancelled();ctx.progress(1.);return result
    return execute

def submit_dissonance_map_job(scheduler,revision_id,a,b,grid=None,model=None,*,estimated_memory_bytes=8*1024*1024):
    return scheduler.submit(JobClass.RESEARCH,revision_id,make_dissonance_map_executor(a,b,grid,model),estimated_memory_bytes=estimated_memory_bytes)

def make_adaptive_tuning_executor(request,state=None):
    if not isinstance(request,AdaptiveTuningRequest):raise JobError('AdaptiveTuningRequest required')
    if state is not None and not isinstance(state,AdaptiveState):raise JobError('AdaptiveState required')
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.1);result=propose_adaptive_tuning(request,state);ctx.check_cancelled();ctx.progress(1.);return result
    return execute

def submit_adaptive_tuning_job(scheduler,revision_id,request,state=None,*,estimated_memory_bytes=8*1024*1024):
    return scheduler.submit(JobClass.ANALYSIS,revision_id,make_adaptive_tuning_executor(request,state),estimated_memory_bytes=estimated_memory_bytes)
