# ZG-009 verification record

Base main: `2590a1428b73a830655a55b0f82a63772f6236a8` (accepted ZG-011).

Local Python 3.13 / NumPy 2.3.5 / SciPy 1.17.0:
- 24 model, contract-integration, real-audio, region-equivalence and HTTP tests passed.
- Node editor tests passed: exact fractional snaps, immutable edits, deterministic
  identity/undo/redo, clips and four-/sixteen-bar construction.
- The existing browser transport's generation/revision/atomic-publication tests
  remain part of the required CI commands.

The local managed Chromium rejected navigation to loopback with
`ERR_BLOCKED_BY_ADMINISTRATOR`. No local browser success is claimed and no browser
policy was bypassed. The exact same acceptance script runs against the real local
server in Windows/Linux GitHub Actions, which must pass before issue closure.

The final PR records actual workflow IDs/head SHA. Browser artifacts include
original 48 kHz WAVs, exact authoring documents, PCM/WAV identities, waveform/event
metadata and the rendered sixteen-bar UI screenshot. No participant data, private
reference recordings or claimed owner listening approvals are included.
