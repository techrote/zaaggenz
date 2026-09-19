# ZG-042 corrective parent-gate marker

ZG-042 corrective acceptance requires the exact final reviewed head to rerun the ZG-029 persistent-layer gate. This marker intentionally changes no layer/audio semantics; its presence in this corrective PR makes the existing path-filtered `zg029-layers.yml` workflow run on the same final head as the long-form repair.
