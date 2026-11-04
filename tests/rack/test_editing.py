"""MBR-003 rack editor: real source-bound Project acceptance, not mocked audio."""
import json
import unittest
from zaaggenz_timeline.model import default_document, compile_recipe
from zaaggenz_timeline.rack_edit import edit_rack, editor_state


class RackEditorTests(unittest.TestCase):
    def setUp(self):
        self.d = default_document(12000)
        self.old = self.d.to_dict()

    def act(self, **kwargs):
        self.d = edit_rack(self.d, kwargs)

    def test_opt_in_preserves_legacy_and_reset(self):
        self.assertFalse(editor_state(self.d)["present"])
        self.act(kind="enable")
        self.assertIn("rack", compile_recipe(self.d).to_dict())
        self.assertEqual(self.d.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])
        self.act(kind="reset")
        self.assertNotIn("rack", compile_recipe(self.d).to_dict())
        self.assertEqual(self.d.to_dict()["notes"], self.old["notes"])
        self.assertEqual(self.d.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])

    def test_stable_insert_identity_controls_and_reopen(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.gain")
        self.act(kind="add", band=band, type_id="zg.compression")
        original = editor_state(self.d)["value"]["bands"][1]["inserts"]
        gain_id, comp_id = [i["id"] for i in original]
        self.act(kind="set", scope="parameter", id=band+"/"+gain_id,
                 field="gain_db", value=4.5)
        self.act(kind="set", scope="parameter", id=band+"/"+comp_id,
                 field="ratio", value=5.0)
        self.act(kind="move", band=band, id=comp_id, step=-1)
        self.act(kind="set", scope="band", id=band, field="confine_delta", value=False)
        self.act(kind="set", scope="rack", id="rack", field="wet", value=0.75)
        self.act(kind="set", scope="crossover", id=1, field="frequency_hz", value=650.0)
        rack = editor_state(self.d)["value"]
        self.assertEqual([i["id"] for i in rack["bands"][1]["inserts"]], [comp_id, gain_id])
        self.assertEqual(rack["bands"][1]["inserts"][1]["params"]["gain_db"], 4.5)
        self.assertFalse(rack["bands"][1]["confine_delta"])
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"], rack)
        self.assertEqual(compile_recipe(reopened).to_dict()["rack"], rack)

    def test_preset_is_source_bound_and_restores_settings(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.bitcrush")
        saved = editor_state(self.d)["value"]
        self.act(kind="save_preset", id="user.crush", name="My rack")
        self.assertEqual(editor_state(self.d)["presets"][0]["id"], "user.crush")
        self.act(kind="set", scope="band", id=band, field="bypass", value=True)
        self.assertNotEqual(editor_state(self.d)["value"], saved)
        self.act(kind="load_preset", id="user.crush")
        self.assertEqual(editor_state(self.d)["value"], saved)

    def test_invalid_actions_do_not_mutate_input(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.compression")
        iid = editor_state(self.d)["value"]["bands"][1]["inserts"][0]["id"]
        before = self.d.to_dict()
        commands = [
            {"kind":"set","scope":"rack","id":"rack","field":"wet","value":True},
            {"kind":"set","scope":"crossover","id":1,"field":"frequency_hz","value":90000},
            {"kind":"set","scope":"parameter","id":band+"/"+iid,"field":"ratio","value":0},
            {"kind":"set","scope":"parameter","id":band+"/"+iid,"field":"unknown","value":1},
            {"kind":"add","band":band,"type_id":"zg.compression"},
            {"kind":"add","band":band,"type_id":"external.vst3"},
            {"kind":"move","band":band,"id":iid,"step":1},
            {"kind":"set","scope":"insert","id":band+"/missing","field":"wet","value":1},
            {"kind":"save_preset","id":"../bad","name":"Bad"},
            {"kind":"reset","unknown":False},
        ]
        for action in commands:
            with self.subTest(action=action):
                with self.assertRaises(ValueError):
                    edit_rack(self.d, action)
                self.assertEqual(self.d.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
