# NYQ-004 experimental controlled-clock PCM bridge

Issue #253, draft PR #267.

**Capability:** opt-in render_controlled_audio_proof in
zaaggenz_dsp/nyquismic_controlled_audio_proof.py, method
nyq.controlled-native-grid-audio-proof.v1. This is a direct PCM
consumer of compiled exact physical-time NYQ-004 events, not merely
an instantaneous control inspector.

The bridge captures immutable NYQ-002 f32 PCM using accepted fractional
source interpolation. It reconstructs hold or physical-time linear audio
on the **original source sampling grid only**, with unchanged duration,
full-extent phase/region ownership, and no implicit resampling, filter or
normalization. The event ledger is hashed separately from region PCM,
including exact rational coordinates, epochs, crossings and certified
uncertainty. Stereo clock events are independently compiled for each
channel, preserving linked/independent jitter identities. Bypass and
wet-zero preserve f32 source bytes; active DSP produces immutable
unclamped f64 output.

**Admission limitations:** sampler mode, physical origin zero, no
prefilter, supported hold/linear reconstruction, finite exact event
geometry, unambiguous native-grid ownership, and source extent within
resource budgets. Irrational ramp roots are rejected if their certified
uncertainty spans two numerical-grid ownership boundaries. Ambiguous
nearest-capture ties reject rather than silently rounding.

**Not qualified:** alternate numerical evaluation rates, persistent
sampler checkpoint, graph/rack/Compose registration, full JobScheduler,
output/export, polyphase delivery conversion, cross-band topology, all
NYQ-004 control modalities, WAV/FLAC demonstrations, human listening
or actual Windows physical testing.

**Direct test:**
python -m unittest discover -s tests/dsp -p 'test_nyquismic_controlled_audio_proof.py' -v

Fixtures cover a hand-derived 8 Hz to 4 Hz step at 1/2 second with
continuous phase, static NYQ-002 PCM parity, time-linear interpolation,
complete-context region equality, stereo linked/independent jitter,
label invariance, bypass, empty source and invalid/cancelled requests.
Ubuntu/Windows CI must pass at the exact PR head before treating this
as a qualified component.

Next, unify this clock with accepted SamplerPlan state/quality under
the appropriate shared-file integration lock, then qualify actual
graph/rack and saved preview/export separately. NYQ-005 stays blocked
until NYQ-003 and NYQ-004 are accepted.
