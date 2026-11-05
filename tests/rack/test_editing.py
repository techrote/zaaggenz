"""MBR-003 rack editor: real source-bound Project acceptance, not mocked audio."""
import json
from copy import deepcopy
import unittest
from zaaggenz_timeline.model import default_document, compile_recipe
from zaaggenz_timeline.rack_edit import edit_rack, editor_state
from zaaggenz_contracts.rack import processor_definition, RackRecipe
from zaaggenz_project import Project
from zaaggenz_spectral.chordness_request import ChordnessRequest
from zaaggenz_spectral.chordness_model import CombTemplate


class RackEditorTests(unittest.TestCase):
    def setUp(self):
        self.d = default_document(12000)
        self.old = self.d.to_dict()

    def act(self, **kwargs):
        self.d = edit_rack(self.d, kwargs)

    def test_preset_draft_context_bound_to_immutable_source_ancestry(self):
        initial = editor_state(self.d)
        root = self.d.to_dict()["project"]["revisions"][0]["id"]
        self.assertEqual(initial["working_context"], root)
        self.act(kind="enable")
        self.assertEqual(editor_state(self.d)["working_context"], root)
        self.act(kind="save_preset", id="user.context", name="Context")
        self.assertEqual(editor_state(self.d)["working_context"], root)
        self.act(kind="reset")
        self.assertEqual(editor_state(self.d)["working_context"], root)
        # The presentation identifier is never included in saved state.
        self.assertNotIn("working_context", self.d.to_dict())
        self.assertNotIn("working_context", self.d.to_dict()["project"])
        other = default_document(48000)
        self.assertNotEqual(editor_state(other)["working_context"], root)

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

    def test_source_bound_spectral_add_after_reset_across_sample_rates(self):
        # The real Compose browser runs at 48 kHz, unlike the smaller
        # default editor fixtures. Re-enable from a dry revision and prove
        # that the added spectral request remains executable and persisted
        # at the source's actual sample rate without rebinding its tuning.
        for sample_rate in (12000, 48000, 96000):
            with self.subTest(sample_rate=sample_rate):
                original = default_document(sample_rate)
                source = compile_recipe(original).to_dict()
                enabled = edit_rack(original, {"kind": "enable"})
                band = editor_state(enabled)["value"]["bands"][1]["id"]
                installed = edit_rack(enabled, {
                    "kind": "add", "band": band, "type_id": "zg.spectral",
                })
                stages = editor_state(installed)["value"]["bands"][1]["inserts"]
                self.assertEqual(len(stages), 1)
                self.assertEqual(stages[0]["type_id"], "zg.spectral")
                params = stages[0]["params"]
                self.assertEqual(params["kind"], "SpectralRetuneRequest")
                self.assertEqual(params["tuning_spec"], source["tuning"])
                self.assertLessEqual(params["max_hz"], sample_rate / 2)
                reopened = type(installed).from_json(json.dumps(installed.to_dict()))
                self.assertEqual(editor_state(reopened)["value"],
                                 editor_state(installed)["value"])
                dry = edit_rack(reopened, {"kind": "reset"})
                self.assertNotIn("rack", compile_recipe(dry).to_dict())
                self.assertEqual(compile_recipe(dry).sha256,
                                 compile_recipe(original).sha256)

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

    def test_parameter_reset_retains_stage_identity_and_nonparameter_policy(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.compression")
        self.act(kind="add", band=band, type_id="zg.gain")
        initial = editor_state(self.d)["value"]["bands"][1]["inserts"]
        compressor_id, gain_id = [item["id"] for item in initial]
        self.act(kind="set", scope="parameter", id=band + "/" + gain_id,
                 field="gain_db", value=9.0)
        self.act(kind="set", scope="insert", id=band + "/" + gain_id,
                 field="wet", value=0.4)
        self.act(kind="set", scope="insert", id=band + "/" + gain_id,
                 field="bypass", value=True)
        before = editor_state(self.d)["value"]
        old_stage = before["bands"][1]["inserts"][1]
        self.act(kind="reset_insert_params", band=band, id=gain_id)
        after = editor_state(self.d)["value"]
        new_stage = after["bands"][1]["inserts"][1]
        self.assertEqual(new_stage["params"], {
            key: value["default"] for key, value in
            processor_definition("zg.gain")["parameters"].items()})
        self.assertEqual({k: v for k, v in new_stage.items() if k != "params"},
                         {k: v for k, v in old_stage.items() if k != "params"})
        self.assertEqual(after["bands"][1]["inserts"][0],
                         before["bands"][1]["inserts"][0])
        self.assertEqual(after["source_binding"], before["source_binding"])
        self.assertEqual(self.d.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])
        self.assertEqual(editor_state(type(self.d).from_json(
            json.dumps(self.d.to_dict())))["value"], after)

    def test_delete_preset_leaves_active_rack_and_source_unmodified(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.gain")
        self.act(kind="save_preset", id="user.first", name="First")
        self.act(kind="save_preset", id="user.second", name="Second")
        before = self.d.to_dict()
        with self.assertRaises(ValueError):
            edit_rack(self.d, {"kind": "delete_preset", "id": "user.absent"})
        self.assertEqual(self.d.to_dict(), before)
        original_recipe = compile_recipe(self.d).to_dict()
        self.act(kind="delete_preset", id="user.first")
        self.assertEqual([row["id"] for row in editor_state(self.d)["presets"]],
                         ["user.second"])
        self.assertEqual(compile_recipe(self.d).to_dict(), original_recipe)
        self.assertEqual(self.d.to_dict()["project"]["revisions"],
                         before["project"]["revisions"])
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["presets"][0]["id"], "user.second")
        with self.assertRaises(ValueError):
            edit_rack(reopened, {"kind": "load_preset", "id": "user.first"})
        self.act(kind="delete_preset", id="user.second")
        self.assertEqual(editor_state(self.d)["presets"], [])
        self.assertEqual(compile_recipe(self.d).to_dict(), original_recipe)

    def test_portable_preset_import_preserves_source_and_hashes(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][2]["id"]
        self.act(kind="add", band=band, type_id="zg.gain")
        iid = editor_state(self.d)["value"]["bands"][2]["inserts"][0]["id"]
        self.act(kind="set", scope="parameter", id=band + "/" + iid,
                 field="gain_db", value=7.5)
        saved = editor_state(self.d)["value"]
        self.act(kind="save_preset", id="user.portable", name="Portable high band")
        entry = self.d.to_dict()["project"]["rack_presets"]["user.portable"]
        record = {"format": "zaaggenz-rack-preset", "version": "1.0.0",
                  **{key: entry[key] for key in
                     ("id", "name", "rack", "rack_sha256", "sonic_sha256")}}
        fresh = default_document(12000)
        self.assertFalse(editor_state(fresh)["present"])
        imported = edit_rack(fresh, {"kind": "import_preset", "record": record})
        self.assertFalse(editor_state(imported)["present"])
        self.assertEqual(editor_state(imported)["presets"][0]["id"], "user.portable")
        reopened = type(imported).from_json(json.dumps(imported.to_dict()))
        restored = edit_rack(reopened, {"kind": "load_preset", "id": "user.portable"})
        self.assertEqual(editor_state(restored)["value"], saved)
        self.assertEqual(compile_recipe(restored).to_dict()["rack"], saved)
        self.assertEqual(fresh.to_dict(), self.old)
        self.assertEqual(restored.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])
        bad = [
            {**record, "version": "2.0.0"},
            {**record, "surprise": 1},
            {**record, "rack_sha256": "0" * 64},
            {**record, "sonic_sha256": "0" * 64},
            {**record, "rack": {**deepcopy(record["rack"]), "wet": .25}},
        ]
        for value in bad:
            with self.subTest(keys=list(value)):
                with self.assertRaises(ValueError):
                    edit_rack(fresh, {"kind": "import_preset", "record": value})
                self.assertEqual(fresh.to_dict(), self.old)
        with self.assertRaises(ValueError):
            edit_rack(imported, {"kind": "import_preset", "record": record})
        foreign = default_document(48000)
        before = foreign.to_dict()
        with self.assertRaises(ValueError):
            edit_rack(foreign, {"kind": "import_preset", "record": record})
        self.assertEqual(foreign.to_dict(), before)

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
            {"kind":"reset_insert_params","band":band,"id":"missing"},
            {"kind":"reset_insert_params","band":band,"id":iid,"surprise":True},
            {"kind":"delete_preset","id":"user.absent"},
            {"kind":"delete_preset","id":"../invalid"},
            {"kind":"delete_preset","id":"user.absent","surprise":False},
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



    def test_source_bound_internal_retune_authoring_survives_reopen(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.compression")
        self.act(kind="add", band=band, type_id="zg.spectral")
        spectral = editor_state(self.d)["value"]["bands"][1]["inserts"][1]
        self.assertEqual(spectral["params"]["kind"], "SpectralRetuneRequest")
        self.assertEqual(spectral["params"]["tuning_spec"],
                         compile_recipe(self.d).to_dict()["tuning"])
        self.assertLessEqual(spectral["params"]["max_hz"], 6000)
        self.act(kind="set", scope="spectral", id=band+"/"+spectral["id"],
                 field="amount", value=.7)
        self.act(kind="set", scope="spectral", id=band+"/"+spectral["id"],
                 field="preserve_ambiguous", value=False)
        self.act(kind="set", scope="spectral_voice", id=band+"/"+spectral["id"],
                 field="degree", value=7)
        self.act(kind="move", band=band, id=spectral["id"], step=-1)
        saved = editor_state(self.d)["value"]
        self.assertEqual(saved["bands"][1]["inserts"][0]["id"], spectral["id"])
        self.assertEqual(saved["bands"][1]["inserts"][0]["params"]["voices"][0]["degree"], 7)
        self.assertEqual(saved["bands"][1]["inserts"][0]["params"]["amount"], .7)
        self.assertFalse(saved["bands"][1]["inserts"][0]["params"]["preserve_ambiguous"])
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"], saved)
        self.assertEqual(compile_recipe(reopened).to_dict()["rack"], saved)
        self.act(kind="remove", band=band, id=spectral["id"])
        self.assertEqual(len(editor_state(self.d)["value"]["bands"][1]["inserts"]), 1)
        self.assertEqual(self.d.to_dict()["project"]["revisions"][0],
                         self.old["project"]["revisions"][0])

    def test_spectral_invalid_intent_is_atomic(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.spectral")
        stage = editor_state(self.d)["value"]["bands"][1]["inserts"][0]
        address = band+"/"+stage["id"]
        before = self.d.to_dict()
        bad = [
            {"kind":"add","band":band,"type_id":"zg.spectral"},
            {"kind":"set","scope":"spectral","id":address,"field":"mode","value":"hybrid"},
            {"kind":"set","scope":"spectral","id":address,"field":"max_hz","value":9000},
            {"kind":"set","scope":"spectral","id":address,"field":"min_confidence","value":True},
            {"kind":"set","scope":"spectral","id":address,"field":"assignment_hysteresis_cents","value":999},
            {"kind":"set","scope":"spectral_voice","id":address,"field":"degree","value":2.5},
            {"kind":"set","scope":"spectral_voice","id":address,"field":"partial_ratios","value":[1,2]},
            {"kind":"set","scope":"chordness_coefficient","id":address,"field":"target_fit","value":5},
            {"kind":"select_spectral_template","band":band,"id":stage["id"],"template_id":"a","value":True},
            {"kind":"set","scope":"spectral","id":address,"field":"amount","value":.5,"extra":False},
            {"kind":"reset_insert_params","band":band,"id":stage["id"]},
        ]
        for action in bad:
            with self.subTest(action=action), self.assertRaises(ValueError):
                edit_rack(self.d, action)
            self.assertEqual(self.d.to_dict(), before)



    def test_retune_multiple_target_voices_and_partial_ratios_are_source_bound(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.spectral")
        stage = editor_state(self.d)["value"]["bands"][1]["inserts"][0]
        sid = stage["id"]
        original_source = compile_recipe(self.d).to_dict()["source"]
        primary = deepcopy(stage["params"]["voices"][0])
        self.act(kind="add_spectral_voice", band=band, id=sid,
                 degree=11, label="Explicit fifth")
        stages = editor_state(self.d)["value"]["bands"][1]["inserts"]
        params = stages[0]["params"]
        self.assertEqual([v["degree"] for v in params["voices"]], [0, 11])
        self.assertEqual(params["voices"][1]["partial_ratios"], primary["partial_ratios"])
        expected = deepcopy(params["voices"][1])
        self.act(kind="edit_spectral_voice", band=band, id=sid, voice_index=1,
                 expected_voice=expected, field="partial_ratios", value=[1., 1.5, 3.])
        expected = deepcopy(editor_state(self.d)["value"]["bands"][1]["inserts"][0]["params"]["voices"][1])
        self.act(kind="edit_spectral_voice", band=band, id=sid, voice_index=1,
                 expected_voice=expected, field="degree", value=12)
        expected = deepcopy(editor_state(self.d)["value"]["bands"][1]["inserts"][0]["params"]["voices"][1])
        self.act(kind="edit_spectral_voice", band=band, id=sid, voice_index=1,
                 expected_voice=expected, field="label", value="New second voice")
        edited = editor_state(self.d)["value"]
        self.assertEqual(edited["bands"][1]["inserts"][0]["params"]["voices"][1],
                         {"degree":12, "partial_ratios":[1., 1.5, 3.],
                          "label":"New second voice"})
        self.assertEqual(compile_recipe(self.d).to_dict()["source"], original_source)
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"], edited)
        before = self.d.to_dict()
        bad = [
            {"kind":"add_spectral_voice","band":band,"id":sid,"degree":True,"label":"invalid"},
            {"kind":"add_spectral_voice","band":band,"id":sid,"degree":1.5,"label":"invalid"},
            {"kind":"add_spectral_voice","band":band,"id":sid,"degree":1,"label":"x"*65},
            {"kind":"add_spectral_voice","band":band,"id":sid,"degree":1,"label":"x","extra":0},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":1,
             "expected_voice":primary,"field":"degree","value":1},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":True,
             "expected_voice":expected,"field":"degree","value":1},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":7,
             "expected_voice":expected,"field":"degree","value":1},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":1,
             "expected_voice":edited["bands"][1]["inserts"][0]["params"]["voices"][1],
             "field":"partial_ratios","value":[1., 1.]},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":1,
             "expected_voice":edited["bands"][1]["inserts"][0]["params"]["voices"][1],
             "field":"partial_ratios","value":[1., True]},
            {"kind":"edit_spectral_voice","band":band,"id":sid,"voice_index":1,
             "expected_voice":edited["bands"][1]["inserts"][0]["params"]["voices"][1],
             "field":"tuning_spec","value":{}},
            {"kind":"remove_spectral_voice","band":band,"id":sid,
             "voice_index":1,"expected_voice":primary},
            {"kind":"remove_spectral_voice","band":band,"id":sid,
             "voice_index":-1,"expected_voice":expected},
        ]
        for command in bad:
            with self.subTest(command=command), self.assertRaises(ValueError):
                edit_rack(self.d, command)
            self.assertEqual(self.d.to_dict(), before)
        current = deepcopy(edited["bands"][1]["inserts"][0]["params"]["voices"][1])
        self.act(kind="remove_spectral_voice", band=band, id=sid,
                 voice_index=1, expected_voice=current)
        self.assertEqual(editor_state(self.d)["value"]["bands"][1]["inserts"][0]["params"]["voices"],
                         [primary])
        with self.assertRaises(ValueError):
            edit_rack(self.d, {"kind":"remove_spectral_voice","band":band,"id":sid,
                               "voice_index":0,"expected_voice":primary})
        self.assertEqual(compile_recipe(self.d).to_dict()["source"], original_source)

    def test_sample_time_retune_segments_are_source_bound_and_stale_guarded(self):
        self.act(kind="enable")
        band = editor_state(self.d)["value"]["bands"][1]["id"]
        self.act(kind="add", band=band, type_id="zg.spectral")
        stage = editor_state(self.d)["value"]["bands"][1]["inserts"][0]
        sid = stage["id"]
        original_source = compile_recipe(self.d).to_dict()["source"]
        original_voice = deepcopy(stage["params"]["voices"][0])
        self.act(kind="add_spectral_segment", band=band, id=sid,
                 start_sample=1200, label="First change", expected_segments=[])
        current = editor_state(self.d)["value"]
        first = current["bands"][1]["inserts"][0]["params"]["segments"][0]
        self.assertEqual(first["voices"], [original_voice])
        before_sonic = RackRecipe(current).sonic_sha256
        self.act(kind="edit_spectral_segment_voice", band=band, id=sid,
                 segment_index=0, expected_segment=deepcopy(first),
                 voice_index=0, value=7)
        current = editor_state(self.d)["value"]
        first = deepcopy(current["bands"][1]["inserts"][0]["params"]["segments"][0])
        self.assertEqual(first["voices"][0]["degree"], 7)
        self.assertNotEqual(RackRecipe(current).sonic_sha256, before_sonic)
        changed_sonic = RackRecipe(current).sonic_sha256
        self.act(kind="edit_spectral_segment", band=band, id=sid,
                 segment_index=0, expected_segment=deepcopy(first),
                 field="label", value="Renamed without DSP change")
        current = editor_state(self.d)["value"]
        self.assertEqual(RackRecipe(current).sonic_sha256, changed_sonic)
        previous = deepcopy(current["bands"][1]["inserts"][0]["params"]["segments"])
        self.act(kind="add_spectral_segment", band=band, id=sid,
                 start_sample=2400, label="Second change",
                 expected_segments=deepcopy(previous))
        current = editor_state(self.d)["value"]
        segments = current["bands"][1]["inserts"][0]["params"]["segments"]
        self.assertEqual([s["start_sample"] for s in segments], [1200, 2400])
        self.assertEqual(segments[1]["voices"], segments[0]["voices"])
        self.assertEqual(compile_recipe(self.d).to_dict()["source"], original_source)
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"], current)
        self.assertEqual(compile_recipe(reopened).to_dict()["rack"], current)

        before = self.d.to_dict()
        stale = deepcopy(previous[0])
        stale["label"] = "Superseded snapshot"
        wrong_stage = "unknown"
        bad = [
            {"kind":"add_spectral_segment","band":band,"id":sid,
             "start_sample":2500,"label":"Changed","expected_segments":[]},
            {"kind":"add_spectral_segment","band":band,"id":sid,
             "start_sample":2400,"label":"Duplicate","expected_segments":segments},
            {"kind":"add_spectral_segment","band":band,"id":sid,
             "start_sample":True,"label":"Boolean","expected_segments":segments},
            {"kind":"add_spectral_segment","band":band,"id":sid,
             "start_sample":2500,"label":"x"*65,"expected_segments":segments},
            {"kind":"add_spectral_segment","band":band,"id":wrong_stage,
             "start_sample":2500,"label":"Absent","expected_segments":segments},
            {"kind":"edit_spectral_segment","band":band,"id":sid,
             "segment_index":0,"expected_segment":stale,
             "field":"start_sample","value":1300},
            {"kind":"edit_spectral_segment","band":band,"id":sid,
             "segment_index":True,"expected_segment":segments[0],
             "field":"label","value":"No"},
            {"kind":"edit_spectral_segment","band":band,"id":sid,
             "segment_index":0,"expected_segment":segments[0],
             "field":"start_sample","value":2400},
            {"kind":"edit_spectral_segment","band":band,"id":sid,
             "segment_index":0,"expected_segment":segments[0],
             "field":"voices","value":[]},
            {"kind":"edit_spectral_segment_voice","band":band,"id":sid,
             "segment_index":0,"expected_segment":segments[0],
             "voice_index":True,"value":5},
            {"kind":"edit_spectral_segment_voice","band":band,"id":sid,
             "segment_index":0,"expected_segment":segments[0],
             "voice_index":0,"value":True},
            {"kind":"edit_spectral_segment_voice","band":band,"id":sid,
             "segment_index":0,"expected_segment":segments[0],
             "voice_index":0,"value":4097},
            {"kind":"remove_spectral_segment","band":band,"id":sid,
             "segment_index":2,"expected_segment":segments[1]},
            {"kind":"remove_spectral_segment","band":band,"id":sid,
             "segment_index":0,"expected_segment":stale},
        ]
        for action in bad:
            with self.subTest(action=action), self.assertRaises(ValueError):
                edit_rack(self.d, action)
            self.assertEqual(self.d.to_dict(), before)

        self.act(kind="remove_spectral_segment", band=band, id=sid,
                 segment_index=1, expected_segment=deepcopy(segments[1]))
        remaining = editor_state(self.d)["value"]["bands"][1]["inserts"][0]["params"]["segments"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["voices"][0]["degree"], 7)
        self.assertEqual(compile_recipe(self.d).to_dict()["source"], original_source)

    def test_existing_chordness_request_preserves_templates_and_edits_scalars(self):
        self.act(kind="enable")
        project = Project.from_document(self.d.to_dict()["project"])
        rack = project.rack.to_dict()
        band = rack["bands"][1]["id"]
        stage_id = "insert.lowmid.spectral"
        chord = ChordnessRequest((
            CombTemplate("root", (100., 200., 300.), 2, "Root", {"method": "manual"}),
            CombTemplate("fifth", (150., 300., 450.), 1, "Fifth", {}),
        ), mode="hybrid", selected_template_ids=("root", "fifth"),
           max_selected_templates=2).to_dict()
        rack["bands"][1]["inserts"].append({
            "id": stage_id, "type_id": "zg.spectral", "version": "1.0.0",
            "bypass": False, "wet": 1.0, "automation": [], "params": chord,
        })
        project.set_rack(RackRecipe(rack))
        original = self.d.to_dict()
        original["project"] = project.to_document()
        self.d = type(self.d)(original)
        addr = band + "/" + stage_id

        self.act(kind="set", scope="spectral", id=addr,
                 field="mode", value="reweight")
        self.act(kind="set", scope="spectral", id=addr,
                 field="min_confidence", value=.4)
        self.act(kind="set", scope="chordness_coefficient", id=addr,
                 field="target_fit", value=2.5)
        self.act(kind="select_spectral_template", band=band, id=stage_id,
                 template_id="root", value=False)
        edited = editor_state(self.d)["value"]["bands"][1]["inserts"][0]["params"]
        self.assertEqual(edited["mode"], "reweight")
        self.assertEqual(edited["selected_template_ids"], ["fifth"])
        self.assertEqual(edited["coefficients"]["target_fit"], 2.5)
        self.assertEqual(edited["templates"], chord["templates"])
        reopened = type(self.d).from_json(json.dumps(self.d.to_dict()))
        self.assertEqual(editor_state(reopened)["value"]["bands"][1]["inserts"][0]["params"],
                         edited)

        before = self.d.to_dict()
        illegal = (
            {"kind": "select_spectral_template", "band": band, "id": stage_id,
             "template_id": "fifth", "value": False},
            {"kind": "select_spectral_template", "band": band, "id": stage_id,
             "template_id": "absent", "value": True},
            {"kind": "select_spectral_template", "band": band, "id": stage_id,
             "template_id": "root", "value": "true"},
            {"kind": "set", "scope": "chordness_coefficient", "id": addr,
             "field": "target_fit", "value": -1},
            {"kind": "set", "scope": "spectral_voice", "id": addr,
             "field": "degree", "value": 2},
        )
        for command in illegal:
            with self.subTest(command=command), self.assertRaises(ValueError):
                edit_rack(self.d, command)
            self.assertEqual(self.d.to_dict(), before)

if __name__ == "__main__":
    unittest.main()
