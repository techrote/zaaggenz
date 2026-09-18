from __future__ import annotations

import unittest

import numpy as np

from tests.layers.test_pockets import CROSSOVERS, _fixture
from zaaggenz_layers import (
    LayerPocketPlan,
    SidechainPocketSpec,
    render_coordinated_layers,
    render_coordinated_pockets,
)


class PocketIntegrationIdentityTests(unittest.TestCase):
    def test_zero_max_sidechain_is_bit_exact_through_full_render(self):
        recipe, progression, runtime = _fixture()
        base = render_coordinated_layers(recipe, progression, ["0/1"], "1/1", runtime)
        plan = LayerPocketPlan(CROSSOVERS, sidechains=(
            SidechainPocketSpec(
                "body", "synthline", "lowmid", threshold_dbfs=-80.0,
                attack_samples=0, release_samples=0, lookahead_samples=0,
                max_attenuation_db=0.0,
            ),
        ))
        result = render_coordinated_pockets(
            recipe, progression, ["0/1"], "1/1", runtime, plan,
        )

        np.testing.assert_array_equal(result.mix, base.mix)
        for name, stem in base.stems.items():
            np.testing.assert_array_equal(result.stems[name], stem)
        self.assertEqual(result.state.to_dict(), base.state.to_dict())
        self.assertEqual(result.diagnostics["pocket_changed_roles"], [])
        self.assertEqual(result.diagnostics["pockets"]["operations"][0]["active_samples"], 0)
        self.assertIsNone(result.diagnostics["pockets"]["operations"][0]["band_delta"])
        self.assertIn("effect-identity bypass", result.diagnostics["pocket_master_path"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
