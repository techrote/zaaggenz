"""Authoritative in-process Compose session identity for the unified local runtime."""
from __future__ import annotations
from copy import deepcopy
import threading
from zaaggenz_project import Project
from zaaggenz_timeline.model import TimelineDocument

FORMAT='zaaggenz-runtime-session'
VERSION='1.0.0'

class RuntimeSession:
    """Own exactly one current immutable TimelineDocument snapshot.

    Research work may retain immutable artefacts from older revisions, but it
    must compare their revision against this owner before publication/apply.
    """
    def __init__(self,document):
        self._lock=threading.RLock();self._generation=0
        self._document=document if isinstance(document,TimelineDocument) else TimelineDocument(document)

    def document(self):
        with self._lock:return TimelineDocument(self._document.to_dict())

    def current_revision_id(self):
        with self._lock:return self._document.revision_id

    def accept_document(self,document):
        candidate=document if isinstance(document,TimelineDocument) else TimelineDocument(document)
        with self._lock:
            if candidate.revision_id!=self._document.revision_id:
                self._document=candidate;self._generation+=1
            return self._snapshot_locked()

    def _snapshot_locked(self):
        data=self._document.to_dict();project=Project.from_document(data['project'])
        return {'format':FORMAT,'version':VERSION,'generation':self._generation,
                'timeline_revision_id':self._document.revision_id,
                'project_revision_id':project.head,'project_sha256':project.sha256}

    def snapshot(self):
        with self._lock:return deepcopy(self._snapshot_locked())
