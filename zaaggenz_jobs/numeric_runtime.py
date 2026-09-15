from __future__ import annotations
import os
import threading
import time
from .model import JobError

_ENV_NAMES=('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS','VECLIB_MAXIMUM_THREADS')
_LOCK=threading.RLock()
_LIMIT=None
_OWNERS=0
_ORIGINAL_ENV=None
_NATIVE_GUARD=None
_DEGRADED=False


def _load_threadpool_limits():
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        return None
    return threadpool_limits


def _restore_env(snapshot):
    for name,value in snapshot.items():
        if value is None: os.environ.pop(name,None)
        else: os.environ[name]=value


class NumericRuntimeLease:
    """Idempotent lease on the one process-wide numerical thread policy."""
    __slots__=('limit','degraded','_released')
    def __init__(self,limit,degraded):
        self.limit=limit;self.degraded=degraded;self._released=False
    def restore_original_limits(self):
        global _LIMIT,_OWNERS,_ORIGINAL_ENV,_NATIVE_GUARD,_DEGRADED
        with _LOCK:
            if self._released:return
            self._released=True
            if _OWNERS<1:raise JobError('numerical runtime ownership underflow')
            _OWNERS-=1
            if _OWNERS:return
            guard=_NATIVE_GUARD;original=_ORIGINAL_ENV
            _LIMIT=None;_ORIGINAL_ENV=None;_NATIVE_GUARD=None;_DEGRADED=False
            try:
                if guard is not None and hasattr(guard,'restore_original_limits'):
                    guard.restore_original_limits()
            finally:
                if original is not None:_restore_env(original)


def numeric_thread_limit(limit=1):
    """Acquire the shared process numerical-thread policy.

    The first owner installs the policy and captures the exact external environment.
    Further owners may share the same limit. A conflicting limit is rejected rather
    than silently changing the process beneath already-running schedulers. The final
    release restores the original native pools (when threadpoolctl is available) and
    the exact pre-ownership environment, independent of scheduler shutdown order.
    """
    global _LIMIT,_OWNERS,_ORIGINAL_ENV,_NATIVE_GUARD,_DEGRADED
    if type(limit)is not int or not 1<=limit<=8:raise JobError('numeric thread limit must be 1..8')
    with _LOCK:
        if _OWNERS:
            if limit!=_LIMIT:
                raise JobError(f'process numerical runtime already owns limit {_LIMIT}; requested {limit}')
            _OWNERS+=1
            return NumericRuntimeLease(limit,_DEGRADED)
        original={name:os.environ.get(name) for name in _ENV_NAMES}
        for name in _ENV_NAMES:os.environ[name]=str(limit)
        factory=_load_threadpool_limits();guard=None
        try:
            if factory is not None:guard=factory(limits=limit)
        except Exception as exc:
            _restore_env(original)
            raise JobError('failed to acquire native numerical thread limit') from exc
        _LIMIT=limit;_OWNERS=1;_ORIGINAL_ENV=original;_NATIVE_GUARD=guard;_DEGRADED=factory is None
        return NumericRuntimeLease(limit,_DEGRADED)


def install_scheduler_construction_guard(cls):
    """Make partial JobScheduler construction release its process runtime lease.

    The legacy constructor acquires the numeric guard before starting workers. If a
    thread start raises after another worker has started, the wrapper marks the
    partial scheduler shut down, gives already-started idle workers a bounded chance
    to exit, then releases the lease. Class identity is preserved for existing
    imports and isinstance checks.
    """
    if getattr(cls,'_process_runtime_construction_guarded',False):return cls
    original=cls.__init__
    def guarded(self,*args,**kwargs):
        try:return original(self,*args,**kwargs)
        except BaseException:
            cv=getattr(self,'_cv',None)
            if cv is not None:
                with cv:
                    self._shutdown=True;cv.notify_all()
            deadline=time.monotonic()+1.0
            for worker in getattr(self,'_threads',()):
                if worker.is_alive():worker.join(max(0.0,deadline-time.monotonic()))
            guard=getattr(self,'_numeric_guard',None)
            if guard is not None:guard.restore_original_limits()
            raise
    cls.__init__=guarded;cls._process_runtime_construction_guarded=True
    return cls


def runtime_state():
    """Diagnostic snapshot used by tests/runtime diagnostics; contains no mutable guard."""
    with _LOCK:return {'limit':_LIMIT,'owners':_OWNERS,'degraded':_DEGRADED}
