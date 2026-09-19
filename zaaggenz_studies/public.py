"""Stable public-report compatibility for the hardened ZG-040 executor."""
from __future__ import annotations

from zaaggenz_contracts import digest

from .corrective import analyse_study as _analyse_study


def analyse_study(*args, **kwargs):
    """Run hardened analysis while preserving the accepted v1 method vocabulary.

    The corrective executor changes allocation strategy, not the statistical
    method.  Keep ``paired-cell-sign-randomisation-v1`` as the report method ID;
    the machine-readable ``resampling`` block records the bounded/streamed
    execution envelope separately.
    """
    report = _analyse_study(*args, **kwargs)
    changed = False
    for section in ("confirmatory", "exploratory"):
        for row in report.get(section, ()):
            if row.get("test_method") == "paired-cell-sign-randomisation-bounded-v1":
                row["test_method"] = "paired-cell-sign-randomisation-v1"
                changed = True
    if changed:
        report.pop("report_sha256", None)
        report["report_sha256"] = digest(
            {"domain": "zaaggenz-study-report-v1-corrective", "report": report}
        )
    return report
