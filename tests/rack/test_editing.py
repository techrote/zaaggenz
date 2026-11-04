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

    def test_remove_stage_preserves_source_and_remaining_instance(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.gain")
        self.act(kind="add", band=band, type_id="zg.compression")
        stages = editor_state(self.d)["value"]["bands"][1]["inserts"]
        gain_id, comp_id = [item["id"] for item in stages]
        self.act(kind="set", scope="parameter", id=band + "/" + gain_id,
                 field="gain_db", value=7.0)
        self.act(kind="remove", band=band, id=comp_id)
        saved = editor_state(self.d)["value"]
        self.assertEqual([item["id"] for item in saved["bands"][1]["inserts"]], [gain_id])
        self.assertEqual(saved["bands"][1]["inserts"][0]["params"]["gain_db"], 7.0)
        self.assertEqual(self.d.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"], saved)
        self.assertEqual(compile_recipe(reopened).to_dict()["rack"], saved)
        with self.assertRaises(ValueError):
            edit_rack(self.d, {"kind": "remove", "band": band, "id": comp_id})
        self.act(kind="reset")
        self.assertNotIn("rack", compile_recipe(self.d).to_dict())

    def test_explicit_preset_replacement_and_name_only_edit(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.gain")
        iid = editor_state(self.d)["value"]["bands"][1]["inserts"][0]["id"]
        self.act(kind="save_preset", id="user.one", name="First")
        self.act(kind="set", scope="parameter", id=band + "/" + iid,
                 field="gain_db", value=6.0)
        edited = editor_state(self.d)["value"]
        with self.assertRaises(ValueError):
            edit_rack(self.d, {"kind": "save_preset", "id": "user.one", "name": "No overwrite"})
        self.act(kind="replace_preset", id="user.one", name="Second")
        self.assertEqual(self.d.to_dict()["project"]["rack_presets"]["user.one"]["rack"], edited)
        self.act(kind="rename_preset", id="user.one", name="Renamed")
        self.assertEqual(editor_state(self.d)["presets"][0]["name"], "Renamed")
        self.assertEqual(self.d.to_dict()["project"]["rack_presets"]["user.one"]["rack"], edited)
        self.act(kind="set", scope="rack", id="rack", field="bypass", value=True)
        self.act(kind="load_preset", id="user.one")
        self.assertEqual(editor_state(self.d)["value"], edited)
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["presets"][0]["name"], "Renamed")

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
            {"kind":"remove","band":band,"id":"missing"},
            {"kind":"remove","band":"unknown","id":iid},
            {"kind":"remove","band":band,"id":iid,"surprise":True},
            {"kind":"replace_preset","id":"unknown","name":"No"},
            {"kind":"rename_preset","id":"unknown","name":"No"},
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
