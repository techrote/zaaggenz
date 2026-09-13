# ZG-027 verification record

Branch: `zg-027/directional-gestures`. Base: accepted ZG-025 merge `063356f976a14da40b755adabbd5f250a403d8e2`.

Final acceptance is produced by `.github/workflows/zg027-gesture.yml` on the final PR head. It runs gesture validation/transformation/compilation tests, inherited ZG-008 melody tests, inherited ZG-025 phrase tests and full-rate matched generated-source fixtures on Ubuntu and Windows. The independent ZG-002 contract/legacy workflow must also pass before merge.

The final PR and issue completion comment record actual head SHA, run IDs and artifact IDs. This file intentionally does not predeclare a CI pass.

Evidence boundaries: `source_family` is authoring metadata while the frozen renderer has one protected source; unsupported timbral axes remain explicit deferred automation; no graph topology is rewritten; playback matching is not perceptual loudness certification; no owner preference or listener-response claim is inferred.
