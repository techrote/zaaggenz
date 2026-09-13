# ZG-026 verification record

Branch: `zg-026/nested-metrical-clocks`. Base: accepted ZG-025 merge `063356f976a14da40b755adabbd5f250a403d8e2`.

Final acceptance is produced by `.github/workflows/zg026-meter.yml` on the final PR head. It runs the meter validation/timing/overlay suite, inherited ZG-012 analysis tests, inherited ZG-025 phrase tests, and the 48 kHz matched stereo clock fixtures on Ubuntu and Windows. The independent ZG-002 contracts/legacy workflow must also pass before merge.

The final PR and issue comment record the actual head SHA, run IDs and artifact IDs. This file intentionally does not predeclare a passing result.

Evidence boundaries: clock support is not a preference score; multiple supported clocks are expected and retained; true 3:2 is explicitly authored rather than inferred from BPM; control bindings are schedules until a later issue explicitly routes them into production DSP; click fixtures are measurement/control evidence rather than zaag audio or owner listening evidence.
