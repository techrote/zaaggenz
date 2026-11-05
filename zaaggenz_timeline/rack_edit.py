"""Bounded MBR-003 Compose rack editing over canonical Project/RackRecipe.

A command returns an uncommitted proposal. RuntimeSession adoption and memory
admission remain in TimelineService.validate, never in a secondary controller.
"""
from __future__ import annotations

from copy import deepcopy
from zaaggenz_contracts.rack import (RackRecipe, empty_rack, processor_definition,
                                    RACK_VERSION, COEFFICIENTS)
from zaaggenz_spectral.model import SpectralRetuneRequest, LatticeVoice
from zaaggenz_project import Project
from .model import TimelineDocument, TimelineError, exact

EDITABLE = ("zg.gain", "zg.compression", "zg.bitcrush")
SPECTRAL = "zg.spectral"
ADDABLE = (*EDITABLE, SPECTRAL)
PORTABLE_PRESET_FORMAT = "zaaggenz-rack-preset"
PORTABLE_PRESET_VERSION = "1.0.0"


def editor_state(document):
    doc = document if isinstance(document, TimelineDocument) else TimelineDocument(document)
    project = Project.from_document(doc.to_dict()["project"])
    return {
        "present": project.rack is not None,
        "value": None if project.rack is None else project.rack.to_dict(),
        "parameters": {kind: processor_definition(kind)["parameters"] for kind in ADDABLE},
        "spectral_coefficients": deepcopy(COEFFICIENTS),
        "presets": [{"id": key, "name": val["name"]}
                    for key, val in sorted(project.rack_presets.items())],
    }


def _band(rack, identifier):
    for row in rack["bands"]:
        if row["id"] == identifier:
            return row
    raise TimelineError("unknown band id")


def _insert(band, identifier):
    for row in band["inserts"]:
        if row["id"] == identifier:
            return row
    raise TimelineError("unknown insert id")


def _update(project, action):
    if project.rack is None:
        raise TimelineError("enable the rack before changing controls")
    rack = project.rack.to_dict()
    kind = action["kind"]
    if kind == "set":
        exact(action, {"kind", "scope", "id", "field", "value"}, "rack set")
        scope, identifier, field, value = (action["scope"], action["id"],
                                            action["field"], action["value"])
        if scope == "rack":
            if identifier != "rack" or field not in ("bypass", "wet"):
                raise TimelineError("unsupported rack control")
            rack[field] = value
        elif scope == "crossover":
            if type(identifier) is not int or identifier not in (0, 1, 2) or field != "frequency_hz":
                raise TimelineError("unsupported crossover control")
            rack["crossovers"]["frequencies_hz"][identifier] = value
        elif scope == "band":
            if field not in ("bypass", "wet", "confine_delta"):
                raise TimelineError("unsupported band control")
            _band(rack, identifier)[field] = value
        elif scope in ("insert", "parameter", "spectral", "spectral_voice", "chordness_coefficient"):
            if type(identifier) is not str or "/" not in identifier:
                raise TimelineError("expected band/insert identity")
            band_id, insert_id = identifier.split("/", 1)
            stage = _insert(_band(rack, band_id), insert_id)
            if scope == "insert":
                if field not in ("bypass", "wet"):
                    raise TimelineError("unsupported insert control")
                stage[field] = value
            elif scope == "parameter":
                definitions = processor_definition(stage["type_id"]).get("parameters", {})
                if stage["type_id"] not in EDITABLE or field not in definitions:
                    raise TimelineError("unsupported processor parameter")
                if "const" in definitions[field] or "enum" in definitions[field]:
                    raise TimelineError("unsupported processor policy edit")
                stage["params"][field] = value
            elif stage["type_id"] == SPECTRAL and type(stage["params"]) is dict:
                # Only the existing, explicitly typed request is editable.
                # Do not replace templates, targets, schedules or tuning
                # implicitly when a single scalar changes.
                params = stage["params"]
                if scope == "spectral":
                    table = processor_definition(SPECTRAL)["parameters"][
                        "retune" if params["kind"] == "SpectralRetuneRequest" else "chordness"
                    ]
                    if field not in table or "const" in table[field]:
                        raise TimelineError("unsupported spectral request field")
                    params[field] = value
                elif scope == "spectral_voice":
                    if (params["kind"] != "SpectralRetuneRequest" or
                            field != "degree" or not params["voices"]):
                        raise TimelineError("unsupported spectral target edit")
                    params["voices"][0]["degree"] = value
                elif scope == "chordness_coefficient":
                    if params["kind"] != "ChordnessRequest" or field not in COEFFICIENTS:
                        raise TimelineError("unsupported Chordness coefficient")
                    params["coefficients"][field] = value
                else:
                    raise TimelineError("unsupported spectral control")
            else:
                raise TimelineError("unsupported processor control")
        else:
            raise TimelineError("unsupported rack control scope")
    elif kind == "add":
        exact(action, {"kind", "band", "type_id"}, "add insert")
        type_id = action["type_id"]
        if type_id not in ADDABLE:
            raise TimelineError("only supported built-in stages can be added")
        band = _band(rack, action["band"])
        if any(i["type_id"] == type_id for i in band["inserts"]):
            raise TimelineError("duplicate built-in stage")
        used = {rack["id"]} | {b["id"] for b in rack["bands"]} | {
            i["id"] for b in rack["bands"] for i in b["inserts"]
        }
        prefix = "insert." + band["band"] + "." + type_id[3:]
        identifier = prefix
        n = 2
        while identifier in used:
            identifier = prefix + "." + str(n)
            n += 1
        if type_id == SPECTRAL:
            # An explicit, executable ZG-017 retune request tied to the
            # accepted source tuning; never invent a new tuning identity.
            # Existing Chordness snapshots remain fully preserved/editable.
            sample_rate = rack["sample_rate_hz"]
            params = SpectralRetuneRequest(
                tuning_spec=project.head_recipe.to_dict()["tuning"],
                voices=(LatticeVoice(0, (1., 2., 3.), "Primary target"),),
                max_hz=min(6000., sample_rate / 2),
            ).to_dict()
        else:
            defs = processor_definition(type_id)["parameters"]
            params = {name: val["default"] for name, val in defs.items()}
        band["inserts"].append({
            "id": identifier, "type_id": type_id, "version": RACK_VERSION,
            "bypass": False, "wet": 1.0, "automation": [],
            "params": params,
        })
    elif kind in ("add_spectral_voice", "edit_spectral_voice", "remove_spectral_voice"):
        # These are explicitly requested authoring edits, never silent
        # re-generation of a saved tuning, voice lattice or target schedule.
        if kind == "add_spectral_voice":
            exact(action, {"kind", "band", "id", "degree", "label"}, "add retune voice")
        elif kind == "edit_spectral_voice":
            exact(action, {"kind", "band", "id", "voice_index", "expected_voice",
                           "field", "value"}, "edit retune voice")
        else:
            exact(action, {"kind", "band", "id", "voice_index", "expected_voice"},
                  "remove retune voice")
        stage = _insert(_band(rack, action["band"]), action["id"])
        if (stage["type_id"] != SPECTRAL or type(stage["params"]) is not dict or
                stage["params"].get("kind") != "SpectralRetuneRequest"):
            raise TimelineError("target voice editing requires a saved retune request")
        voices = stage["params"]["voices"]
        if kind == "add_spectral_voice":
            if len(voices) >= 32:
                raise TimelineError("retune target has the maximum 32 voices")
            # Displayed in Compose: inherit the primary voice's partial ratios,
            # but require the user to choose the degree and label explicitly.
            # LatticeVoice and RackRecipe enforce all numerical/work bounds.
            added = LatticeVoice(action["degree"],
                                 tuple(voices[0]["partial_ratios"]), action["label"])
            voices.append(added.to_dict())
        else:
            index = action["voice_index"]
            if type(index) is not int or not 0 <= index < len(voices):
                raise TimelineError("unknown retune voice index")
            if type(action["expected_voice"]) is not dict or voices[index] != action["expected_voice"]:
                raise TimelineError("retune voice changed; refresh before editing")
            if kind == "remove_spectral_voice":
                if len(voices) == 1:
                    raise TimelineError("a retune request must retain at least one voice")
                voices.pop(index)
            else:
                field = action["field"]
                if field not in ("degree", "label", "partial_ratios"):
                    raise TimelineError("unsupported retune voice field")
                # No unchecked coercion of booleans, paths or unknown payloads.
                voices[index][field] = action["value"]
        # Full source, schedule, target-lattice and memory validation occurs
        # below, before the detached proposal can enter RuntimeSession.
    elif kind in ("add_spectral_segment", "edit_spectral_segment",
                  "remove_spectral_segment", "edit_spectral_segment_voice"):
        # All schedule changes are detached source-bound proposals. A complete
        # expected snapshot prevents stale position-based edits, including when
        # another queued command inserts, removes or relabels a segment.
        if kind == "add_spectral_segment":
            exact(action, {"kind", "band", "id", "start_sample", "label",
                           "expected_segments"}, "add retune segment")
        elif kind == "edit_spectral_segment":
            exact(action, {"kind", "band", "id", "segment_index",
                           "expected_segment", "field", "value"}, "edit retune segment")
        elif kind == "edit_spectral_segment_voice":
            exact(action, {"kind", "band", "id", "segment_index",
                           "expected_segment", "voice_index", "value"},
                  "edit retune segment voice")
        else:
            exact(action, {"kind", "band", "id", "segment_index",
                           "expected_segment"}, "remove retune segment")
        stage = _insert(_band(rack, action["band"]), action["id"])
        if (stage["type_id"] != SPECTRAL or type(stage["params"]) is not dict or
                stage["params"].get("kind") != "SpectralRetuneRequest"):
            raise TimelineError("retune schedule editing requires a saved retune request")
        params = stage["params"]
        segments = params["segments"]
        if kind == "add_spectral_segment":
            if (type(action["expected_segments"]) is not list or
                    action["expected_segments"] != segments):
                raise TimelineError("retune schedule changed; refresh before adding")
            start = action["start_sample"]
            label = action["label"]
            if type(start) is not int or not 1 <= start <= 192000 * 3600:
                raise TimelineError("segment start_sample must be a bounded positive integer")
            if type(label) is not str or len(label) > 64:
                raise TimelineError("segment label must be at most 64 characters")
            if len(segments) >= 64:
                raise TimelineError("retune schedule has the maximum 64 segments")
            if segments and start <= segments[-1]["start_sample"]:
                raise TimelineError("new segment must start after the last segment")
            # An explicit new change-point inherits the immediately previous
            # target lattice, or the initial target for the first change-point.
            # Only a subsequent user edit changes its sonic target.
            previous = segments[-1]["voices"] if segments else params["voices"]
            segments.append({"start_sample": start,
                             "voices": deepcopy(previous), "label": label})
        else:
            index = action["segment_index"]
            if type(index) is not int or not 0 <= index < len(segments):
                raise TimelineError("unknown retune segment index")
            segment = segments[index]
            if (type(action["expected_segment"]) is not dict or
                    action["expected_segment"] != segment):
                raise TimelineError("retune segment changed; refresh before editing")
            if kind == "remove_spectral_segment":
                segments.pop(index)
            elif kind == "edit_spectral_segment":
                field = action["field"]
                if field not in ("start_sample", "label"):
                    raise TimelineError("unsupported retune segment field")
                segment[field] = action["value"]
            else:
                voice_index = action["voice_index"]
                if type(voice_index) is not int or not 0 <= voice_index < len(segment["voices"]):
                    raise TimelineError("unknown retune segment voice")
                # The accepted rack validator checks type/range, schedule
                # ordering, sample-rate/resource limits and source ancestry.
                segment["voices"][voice_index]["degree"] = action["value"]
        # Never modify source tuning, unrelated segments, or export policy.
        # The RackRecipe below validates the complete candidate atomically.
    elif kind == "select_spectral_template":
        exact(action, {"kind", "band", "id", "template_id", "value"},
              "select spectral template")
        stage = _insert(_band(rack, action["band"]), action["id"])
        if (stage["type_id"] != SPECTRAL or type(stage["params"]) is not dict or
                stage["params"].get("kind") != "ChordnessRequest"):
            raise TimelineError("template selection requires an installed Chordness request")
        if type(action["value"]) is not bool:
            raise TimelineError("template selection must be boolean")
        template_id = action["template_id"]
        params = stage["params"]
        if type(template_id) is not str or template_id not in {
            item["id"] for item in params["templates"]
        }:
            raise TimelineError("unknown Chordness template")
        selected = params["selected_template_ids"]
        if action["value"] and template_id not in selected:
            selected.append(template_id)
        elif not action["value"] and template_id in selected:
            selected.remove(template_id)
        # RackRecipe performs all cardinality, mode and confidence checks.
    elif kind == "move":
        exact(action, {"kind", "band", "id", "step"}, "move insert")
        if type(action["step"]) is not int or action["step"] not in (-1, 1):
            raise TimelineError("move step must be -1 or 1")
        band = _band(rack, action["band"])
        index = next((i for i, v in enumerate(band["inserts"])
                      if v["id"] == action["id"]), None)
        if index is None or not 0 <= index + action["step"] < len(band["inserts"]):
            raise TimelineError("insert cannot move beyond band boundary")
        target = index + action["step"]
        band["inserts"][index], band["inserts"][target] = (
            band["inserts"][target], band["inserts"][index])
    elif kind == "reset_insert_params":
        exact(action, {"kind", "band", "id"}, "reset insert parameters")
        stage = _insert(_band(rack, action["band"]), action["id"])
        if stage["type_id"] not in EDITABLE:
            raise TimelineError("only supported built-in parameters can be reset")
        # Parameter reset is not stage replacement: stable ID, wet/bypass,
        # order, labels and source binding are all retained verbatim.
        definitions = processor_definition(stage["type_id"])["parameters"]
        stage["params"] = {name: definition["default"] for name, definition in definitions.items()}
    elif kind == "remove":
        exact(action, {"kind", "band", "id"}, "remove insert")
        band = _band(rack, action["band"])
        stage = _insert(band, action["id"])
        # Preserve opaque/unimplemented processor state; only editable
        # built-in stages can be removed through this authoring command.
        if stage["type_id"] not in ADDABLE:
            raise TimelineError("only supported built-in stages can be removed")
        band["inserts"] = [item for item in band["inserts"] if item["id"] != stage["id"]]
        rack["display"].pop(stage["id"], None)
    else:
        raise TimelineError("unknown rack update kind")
    saved = RackRecipe(rack)  # all latent fields validated, including bypass
    saved.require_source(project.head_recipe)
    project.set_rack(saved)


def edit_rack(document, action):
    """Edit a detached project copy; reject unknown keys and invalid intent."""
    doc = document if isinstance(document, TimelineDocument) else TimelineDocument(document)
    if type(action) is not dict or type(action.get("kind")) is not str:
        raise TimelineError("rack action requires kind")
    project = Project.from_document(doc.to_dict()["project"])
    kind = action["kind"]
    if kind in ("enable", "reset"):
        exact(action, {"kind"}, "rack lifecycle")
        if kind == "enable":
            if project.rack is not None:
                raise TimelineError("rack already exists")
            project.set_rack(empty_rack(project.head_recipe))
        else:
            if project.rack is None:
                raise TimelineError("no rack to reset")
            project.reset_rack()
    elif kind == "save_preset":
        exact(action, {"kind", "id", "name"}, "save rack preset")
        project.save_rack_preset(action["id"], action["name"])
    elif kind == "load_preset":
        exact(action, {"kind", "id"}, "load rack preset")
        project.apply_rack_preset(action["id"])
    elif kind == "replace_preset":
        exact(action, {"kind", "id", "name"}, "replace rack preset")
        if type(action["id"]) is not str or action["id"] not in project.rack_presets:
            raise TimelineError("cannot replace an unknown rack preset")
        project.save_rack_preset(action["id"], action["name"], replace=True)
    elif kind == "rename_preset":
        exact(action, {"kind", "id", "name"}, "rename rack preset")
        if type(action["id"]) is not str:
            raise TimelineError("rack preset id must be a string")
        project.rename_rack_preset(action["id"], action["name"])
    elif kind == "delete_preset":
        exact(action, {"kind", "id"}, "delete rack preset")
        # Retain the existing project contract and immutable revisions.
        # Full Project reload validates the changed user inventory atomically,
        # without editing the frozen core Project/rack-state implementation.
        identifier = action["id"]
        stored = project.to_document()
        if type(identifier) is not str or identifier not in stored.get("rack_presets", {}):
            raise TimelineError("unknown user rack preset")
        del stored["rack_presets"][identifier]
        project = Project.from_document(stored)
    elif kind == "import_preset":
        # An imported snapshot has no permission to rebind a different source,
        # inject a revision, or silently replace an existing user preset.
        exact(action, {"kind", "record"}, "import rack preset")
        record = action["record"]
        required = {"format", "version", "id", "name", "rack",
                    "rack_sha256", "sonic_sha256"}
        if type(record) is not dict or set(record) != required:
            raise TimelineError("invalid portable rack preset record")
        if (record["format"] != PORTABLE_PRESET_FORMAT or
                record["version"] != PORTABLE_PRESET_VERSION):
            raise TimelineError("unsupported portable rack preset format/version")
        imported = RackRecipe(record["rack"])
        if (record["rack_sha256"] != imported.sha256 or
                record["sonic_sha256"] != imported.sonic_sha256):
            raise TimelineError("portable rack preset digest mismatch")
        # Project proves retained no-rack ancestry and exact source binding.
        project.save_rack_preset(record["id"], record["name"], imported)
    elif kind in ("set", "add", "move", "remove", "reset_insert_params",
                  "select_spectral_template", "add_spectral_voice",
                  "edit_spectral_voice", "remove_spectral_voice",
                  "add_spectral_segment", "edit_spectral_segment",
                  "remove_spectral_segment", "edit_spectral_segment_voice"):
        _update(project, action)
    else:
        raise TimelineError("unsupported rack action")
    result = doc.to_dict()
    result["project"] = project.to_document()
    return TimelineDocument(result)
