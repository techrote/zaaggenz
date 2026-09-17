import unittest

from tools.inverse_staged_report import _budget_accounting_ok


class StagedReportBudgetIntegrityTests(unittest.TestCase):
    @staticmethod
    def staged(*, method='zg024d.staged-balanced.v2', consumed=24,
               stage=None, stop=None, best=0.25, final=2):
        return {
            'family': 'staged',
            'method_id': method,
            'declared_budget': 24,
            'consumed_evaluations': consumed,
            'stage_consumption': {'A': 8, 'B': 8, 'C': 8} if stage is None else stage,
            'stop_reason': stop,
            'best_fit_score': best,
            'final_retained_count': final,
        }

    def test_complete_frozen_allocations_are_exact(self):
        cases = (
            ('zg024d.staged-balanced.v2', {'A': 8, 'B': 8, 'C': 8}),
            ('zg024d.staged-structure.v2', {'A': 10, 'B': 7, 'C': 7}),
            ('zg024d.staged-texture.v2', {'A': 7, 'B': 7, 'C': 10}),
        )
        for method, stage in cases:
            with self.subTest(method=method):
                self.assertTrue(_budget_accounting_ok(self.staged(method=method, stage=stage)))

    def test_each_fail_closed_stage_prefix_is_valid_exact_accounting(self):
        cases = (
            ('stage-A-no-eligible-parent', 8, {'A': 8, 'B': 0, 'C': 0}),
            ('stage-B-no-eligible-parent', 16, {'A': 8, 'B': 8, 'C': 0}),
            ('stage-C-no-eligible-final-alternative', 24, {'A': 8, 'B': 8, 'C': 8}),
        )
        for stop, consumed, stage in cases:
            with self.subTest(stop=stop):
                row = self.staged(consumed=consumed, stage=stage, stop=stop, best=None, final=0)
                self.assertTrue(_budget_accounting_ok(row))

    def test_early_stop_cannot_smuggle_downstream_work_or_a_selected_candidate(self):
        bad = (
            self.staged(consumed=9, stage={'A': 8, 'B': 1, 'C': 0},
                        stop='stage-A-no-eligible-parent', best=None, final=0),
            self.staged(consumed=8, stage={'A': 8, 'B': 0, 'C': 0},
                        stop='stage-A-no-eligible-parent', best=0.1, final=0),
            self.staged(consumed=8, stage={'A': 8, 'B': 0, 'C': 0},
                        stop='stage-A-no-eligible-parent', best=None, final=1),
            self.staged(consumed=8, stage={'A': 8, 'B': 0, 'C': 0},
                        stop='invented-stop', best=None, final=0),
        )
        for index, row in enumerate(bad):
            with self.subTest(index=index):
                self.assertFalse(_budget_accounting_ok(row))

    def test_no_stop_requires_the_complete_declared_budget(self):
        self.assertFalse(_budget_accounting_ok(
            self.staged(consumed=23, stage={'A': 8, 'B': 8, 'C': 7})))
        self.assertFalse(_budget_accounting_ok(
            self.staged(consumed=24, stage={'A': 8, 'B': 8, 'C': 8}, final=0)))

    def test_flat_baseline_exact_boundary_is_unchanged(self):
        row = {
            'family': 'baseline', 'method_id': 'zg024b.halton-shifted.v1',
            'declared_budget': 24, 'consumed_evaluations': 24,
            'stage_consumption': None, 'stop_reason': None,
            'best_fit_score': 0.2, 'final_retained_count': None,
        }
        self.assertTrue(_budget_accounting_ok(row))
        row['consumed_evaluations'] = 23
        self.assertFalse(_budget_accounting_ok(row))


if __name__ == '__main__':
    unittest.main()
