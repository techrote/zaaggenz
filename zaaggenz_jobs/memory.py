"""Shared admission policy for job wrappers that know a trusted memory floor."""
from __future__ import annotations

from .model import JobError


def authoritative_memory_reservation(minimum_bytes, requested_bytes=None):
    """Return a caller reservation without allowing it below a trusted minimum.

    Wrappers derive ``minimum_bytes`` from the concrete workload (or retain an
    already-accepted fixed floor).  A caller may reserve more for a conservative
    integration environment, but cannot forge a lower value and thereby bypass
    scheduler admission.  The scheduler remains authoritative for its configured
    per-job and lane maxima.
    """
    if type(minimum_bytes) is not int or minimum_bytes <= 0:
        raise JobError('authoritative job memory estimate must be a positive integer')
    if requested_bytes is None:
        return minimum_bytes
    if type(requested_bytes) is not int or requested_bytes <= 0:
        raise JobError('job memory override must be a positive integer')
    if requested_bytes < minimum_bytes:
        raise JobError('job memory override is below the authoritative minimum')
    return requested_bytes
