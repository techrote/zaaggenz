"""Thin ZG-004 RESEARCH-lane adapter, not another scheduler."""
from zaaggenz_jobs import JobClass
from .contracts import require
from .engine import FitProblem, run_baseline


def submit_inverse_job(scheduler, revision_id, problem, *, checkpoint_path=None, resume=None,
                       on_checkpoint=lambda _: None):
    require(isinstance(problem, FitProblem), 'FitProblem required')
    declared = problem.request.to_dict()['source_revision_id']
    require(declared is None or declared == revision_id, 'job revision disagrees with source revision')
    # Conservative admission estimate; like ZG-004 this is not a hard RSS sandbox.
    samples_bytes = len(problem.renderer.source.pcm) + sum(len(t.pcm) for _, t in problem.fitting_targets)
    estimate = 32 * 1024 * 1024 + samples_bytes * 80 + problem.request.budget.evaluations * 40000
    def execute(context):
        return run_baseline(problem, resume=resume, check_cancelled=context.check_cancelled,
                            progress=context.progress, on_checkpoint=on_checkpoint, checkpoint_path=checkpoint_path)
    return scheduler.submit(JobClass.RESEARCH, revision_id, execute, estimated_memory_bytes=estimate)
