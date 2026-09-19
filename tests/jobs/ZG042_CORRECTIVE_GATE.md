# ZG-042 corrective parent-gate marker

ZG-042 corrective acceptance requires the exact final reviewed head to rerun the ZG-004 bounded-scheduler gate. This marker intentionally changes no scheduler semantics; its presence in this corrective PR makes the existing path-filtered `zg004-jobs.yml` workflow run on the same final head as the long-form repair.
