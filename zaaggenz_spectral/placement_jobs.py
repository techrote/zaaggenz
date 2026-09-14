from __future__ import annotations
import numpy as np
from zaaggenz_jobs import JobClass,JobError
from .model import SpectralRetuneRequest
from .placement import NonlinearStageSpec,PlacementRequest,run_family,run_placement


def estimate_placement_memory_bytes(source,variants=1):
    a=np.asarray(source)
    if a.ndim not in (1,2) or not np.issubdtype(a.dtype,np.number):raise JobError('numeric mono/stereo source required')
    if type(variants)is not int or not 1<=variants<=3:raise JobError('variants must be 1..3')
    return max(1,int(a.nbytes*(12+8*variants)+4*1024*1024))


def make_placement_executor(source,sample_rate_hz,request):
    if not isinstance(request,PlacementRequest):raise JobError('PlacementRequest required')
    frozen=np.asarray(source).copy()
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.02);result=run_placement(frozen,sample_rate_hz,request,checkpoint=ctx.check_cancelled);ctx.progress(1.);return result
    return execute


def submit_placement_job(scheduler,revision_id,source,sample_rate_hz,request,*,estimated_memory_bytes=None):
    estimate=estimate_placement_memory_bytes(source,1) if estimated_memory_bytes is None else estimated_memory_bytes
    return scheduler.submit(JobClass.RENDER,revision_id,make_placement_executor(source,sample_rate_hz,request),estimated_memory_bytes=estimate)


def make_family_executor(source,sample_rate_hz,spectral,stage_a,stage_b):
    if not isinstance(spectral,SpectralRetuneRequest) or not isinstance(stage_a,NonlinearStageSpec) or not isinstance(stage_b,NonlinearStageSpec):raise JobError('spectral request and two nonlinear stages required')
    frozen=np.asarray(source).copy()
    def execute(ctx):
        ctx.check_cancelled();ctx.progress(.02)
        out={}
        for i,placement in enumerate(('pre','inter','post')):
            ctx.check_cancelled();out[placement]=run_placement(frozen,sample_rate_hz,PlacementRequest(spectral,placement,stage_a,stage_b),checkpoint=ctx.check_cancelled);ctx.progress(.05+.3*(i+1))
        ctx.progress(1.);return out
    return execute


def submit_placement_family_job(scheduler,revision_id,source,sample_rate_hz,spectral,stage_a,stage_b,*,estimated_memory_bytes=None):
    estimate=estimate_placement_memory_bytes(source,3) if estimated_memory_bytes is None else estimated_memory_bytes
    return scheduler.submit(JobClass.RENDER,revision_id,make_family_executor(source,sample_rate_hz,spectral,stage_a,stage_b),estimated_memory_bytes=estimate)
