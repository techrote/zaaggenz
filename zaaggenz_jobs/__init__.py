"""Bounded local asynchronous job scheduling for zaaggenz."""
from . import model as _model
from .numeric_runtime import (numeric_thread_limit as _numeric_thread_limit,
                              runtime_state,install_scheduler_construction_guard)

# Keep the established model/scheduler API while making its guard process-owned.
# Package initialization always precedes submodule import, so scheduler's existing
# `from .model import numeric_thread_limit` receives this shared lease factory.
_model.numeric_thread_limit=_numeric_thread_limit

from .model import (JobClass, JobState, SchedulerLimits, JobError, JobCancelled,
                    RenderArtifact, atomic_publish_bytes)
from .scheduler import JobScheduler
install_scheduler_construction_guard(JobScheduler)
from .api import RenderCoordinator, RequestTicket

__all__ = ['JobClass','JobState','SchedulerLimits','JobError','JobCancelled',
           'RenderArtifact','atomic_publish_bytes','JobScheduler','RenderCoordinator','RequestTicket','runtime_state']
