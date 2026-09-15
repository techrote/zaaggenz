"""Bounded in-memory local capture store.

Persistent authoring records contain identities, never raw PCM.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import io
import threading

import numpy as np
from scipy.io import wavfile

from .model import VocalCaptureError


class SessionAudioStore:
    def __init__(self, max_items=4, max_seconds=30):
        self.max_items = max_items
        self.max_seconds = max_seconds
        self._items = OrderedDict()
        self._lock = threading.Lock()

    def put(self, audio, sr, origin="local-import"):
        a = np.asarray(audio)
        if a.ndim == 1:
            a = a[:, None]
        if a.ndim != 2 or a.shape[1] not in (1, 2) or not np.isfinite(a).all():
            raise VocalCaptureError("finite mono/stereo PCM required")
        if type(sr) is not int or not 8000 <= sr <= 192000 or not 0 < len(a) <= sr * self.max_seconds:
            raise VocalCaptureError("capture sample rate/duration outside local limits")
        x = np.asarray(a, dtype=np.float32)
        raw = np.asarray(x, dtype="<f4", order="C").tobytes(order="C")
        sha = hashlib.sha256(raw).hexdigest()
        identifier = "capture-" + sha[:16]
        with self._lock:
            self._items[identifier] = (x, sr, origin)
            self._items.move_to_end(identifier)
            while len(self._items) > self.max_items:
                self._items.popitem(last=False)
        return identifier

    def get(self, identifier):
        with self._lock:
            if identifier not in self._items:
                raise VocalCaptureError("capture audio is no longer available in this local session")
            x, sr, origin = self._items[identifier]
            self._items.move_to_end(identifier)
            return x.copy(), sr, origin

    def discard(self, identifier):
        with self._lock:
            return self._items.pop(identifier, None) is not None

    def has(self, identifier):
        with self._lock:
            return identifier in self._items


def _normalise_wav_samples(samples):
    """Return the canonical float32 PCM interpretation of scipy WAV samples.

    RIFF/WAVE PCM with eight or fewer bits is unsigned.  For the supported
    8-bit representation, code 128 is digital zero and the negative endpoint
    has one extra code: 0 -> -1.0, 128 -> 0.0, 255 -> 127/128.  Signed PCM
    keeps the existing full-scale convention of division by the magnitude of
    the most-negative integer.  SciPy exposes 24-bit PCM left-justified in an
    int32 container, so that same signed rule preserves its amplitude.
    """
    x = np.asarray(samples)
    if x.dtype == np.dtype(np.uint8):
        return (x.astype(np.float32) - np.float32(128.0)) / np.float32(128.0)
    if np.issubdtype(x.dtype, np.unsignedinteger):
        raise VocalCaptureError(f"unsupported unsigned WAV PCM dtype: {x.dtype}")
    if np.issubdtype(x.dtype, np.signedinteger):
        info = np.iinfo(x.dtype)
        scale = float(max(-int(info.min), int(info.max)))
        return x.astype(np.float32) / scale
    if np.issubdtype(x.dtype, np.floating):
        return x.astype(np.float32)
    raise VocalCaptureError("numeric PCM/float WAV required")


def decode_wav_bytes(payload, max_bytes=20_000_000):
    if type(payload) not in (bytes, bytearray) or not 44 <= len(payload) <= max_bytes:
        raise VocalCaptureError("WAV upload is empty or exceeds 20 MB")
    try:
        sr, x = wavfile.read(io.BytesIO(payload))
    except Exception as exc:
        raise VocalCaptureError("valid PCM/float WAV required") from exc
    if x.ndim not in (1, 2) or (x.ndim == 2 and x.shape[1] not in (1, 2)):
        raise VocalCaptureError("mono/stereo WAV required")
    x = _normalise_wav_samples(x)
    if not np.isfinite(x).all():
        raise VocalCaptureError("WAV contains non-finite samples")
    return int(sr), x


def encode_wav_bytes(audio, sr):
    b = io.BytesIO()
    wavfile.write(b, int(sr), np.asarray(audio, dtype=np.float32))
    return b.getvalue()
