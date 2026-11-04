"""Bounded MBR-003 Compose rack editing over canonical Project/RackRecipe.

A command returns an uncommitted proposal. RuntimeSession adoption and memory
admission remain in TimelineService.validate, never in a secondary controller.
"""
from __future__ import annotations

from zaaggenz_contracts.rack import RackRecipe, empty_rack, processor_definition, RACK_VERSION
from zaaggenz_project import Project
from .model import TimelineDocument, TimelineError, exact

EDITABLE = ("zg.gain", "zg.compression", "zg.bitcrush")


def editor_state(document):
    doc = document if isinstance(document, TimelineDocument) else TimelineDocument(document)
    project = Project.from_document(doc.to_dict()["project"])
    return {
        "present": project.rack is not None,
        "value": None if project.rack is None else project.rack.to_dict(),
        "parameters": {kind: processor_definition(kind)["parameters"] for kind in EDITABLE},
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
        elif scope in ("insert", "parameter"):
            if type(identifier) is not str or "/" not in identifier:
                raise TimelineError("expected band/insert identity")
            band_id, insert_id = identifier.split("/", 1)
            stage = _insert(_band(rack, band_id), insert_id)
            if scope == "insert":
                if field not in ("bypass", "wet"):
                    raise TimelineError("unsupported insert control")
                stage[field] = value
            else:
                definitions = processor_definition(stage["type_id"]).get("parameters", {})
                if stage["type_id"] not in EDITABLE or field not in definitions:
                    raise TimelineError("unsupported processor parameter")
                if "const" in definitions[field] or "enum" in definitions[field]:
                    raise TimelineError("unsupported processor policy edit")
                stage["params"][field] = value
        else:
            raise TimelineError("unsupported rack control scope")
    elif kind == "add":
        exact(action, {"kind", "band", "type_id"}, "add insert")
        type_id = action["type_id"]
        if type_id not in EDITABLE:
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
        defs = processor_definition(type_id)["parameters"]
        band["inserts"].append({
            "id": identifier, "type_id": type_id, "version": RACK_VERSION,
            "bypass": False, "wet": 1.0, "automation": [],
            "params": {name: val["default"] for name, val in defs.items()},
        })
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
    elif kind == "remove":
        exact(action, {"kind", "band", "id"}, "remove insert")
        band = _band(rack, action["band"])
        stage = _insert(band, action["id"])
        # Preserve opaque/unimplemented processor state; only editable
        # built-in stages can be removed through this authoring command.
        if stage["type_id"] not in EDITABLE:
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
    elif kind in ("set", "add", "move", "remove"):
        _update(project, action)
    else:
        raise TimelineError("unsupported rack action")
    result = doc.to_dict()
    result["project"] = project.to_document()
    return TimelineDocument(result)
