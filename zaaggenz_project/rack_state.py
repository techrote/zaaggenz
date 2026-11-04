"""MBR-001 Project extension. No parallel project store, source rewrite or DSP.

Revision records remain immutable. Presets retain their exact source ancestor;
applying one to another source is an explicit error, never an implicit rebind.
"""
from copy import deepcopy
import json
import re

from zaaggenz_contracts import Contract, ContractError
from zaaggenz_contracts.model import check_json, MAX_BYTES
from zaaggenz_contracts.rack import (RackRecipe, ID_PATTERN, with_rack)
from .project import ProjectError

FORMAT_VERSION = '1.1.0'
MAX_RACK_PRESETS = 32


def _require(condition, message):
    if not condition:
        raise ProjectError(message)


def _name(name):
    _require(type(name) is str and 1 <= len(name) <= 128
             and not any(ord(c) < 32 for c in name), 'invalid user rack preset name')
    check_json(name)


def _id(identifier):
    _require(type(identifier) is str and re.fullmatch(ID_PATTERN, identifier) is not None,
             'invalid user rack preset id')


def source_ancestor(project, rack, *, parent=None):
    """Resolve a real no-rack ancestor, not just a syntactically valid hash.

    parent=None means the current head for authoring. Explicit callers loading
    revision records pass that record's parent; root rack revisions are rejected
    by validate_revision rather than falling back to the head.
    """
    saved = rack if isinstance(rack, RackRecipe) else RackRecipe(rack)
    origin = saved.to_dict()['source_binding']['origin_recipe_sha256']
    current = project.head if parent is None else parent
    seen = set()
    while current is not None:
        _require(current not in seen and current in project._revisions,
                 'rack source ancestry is cyclic or missing')
        seen.add(current)
        record = project._revisions[current]
        if record['recipe_sha256'] == origin:
            recipe = Contract.from_json(record['recipe_json'])
            _require('rack' not in recipe.to_dict(), 'rack origin must be a no-rack source revision')
            saved.require_source(recipe)
            return current, recipe
        current = record['parent']
    raise ProjectError('rack source origin is not a retained no-rack ancestor')


def validate_revision(project, recipe, parent):
    data = recipe.to_dict()
    if 'rack' not in data:
        return
    _require(parent is not None, 'rack working copy requires a retained no-rack source revision')
    rack = RackRecipe(data['rack'])
    rack.require_source(recipe)
    source_ancestor(project, rack, parent=parent)


def validate_presets(project):
    presets = project._rack_presets
    _require(type(presets) is dict and len(presets) <= MAX_RACK_PRESETS,
             'invalid/bounded rack preset collection')
    for identifier, entry in presets.items():
        _id(identifier)
        _require(type(entry) is dict and set(entry) == {
            'id', 'name', 'rack', 'source_revision_id', 'rack_sha256', 'sonic_sha256'},
            'invalid user rack preset record')
        _require(identifier == entry['id'], 'user rack preset id mismatch')
        _name(entry['name'])
        rack = RackRecipe(entry['rack'])
        _require(rack.sha256 == entry['rack_sha256'], 'rack preset snapshot hash mismatch')
        _require(rack.sonic_sha256 == entry['sonic_sha256'], 'rack preset sonic hash mismatch')
        source_id = entry['source_revision_id']
        _require(type(source_id) is str and source_id in project._revisions,
                 'rack preset source revision is missing')
        source = Contract.from_json(project._revisions[source_id]['recipe_json'])
        _require('rack' not in source.to_dict() and source.sha256 ==
                 rack.to_dict()['source_binding']['origin_recipe_sha256'],
                 'rack preset source provenance mismatch')
        rack.require_source(source)
        # Every record must be on the retained lineage, not a detached/future source.
        source_ancestor(project, rack)


def bounded_document(document):
    """The same limits used by the actual load path, before any v1.1 mutation."""
    try:
        check_json(document)
        raw = json.dumps(document, ensure_ascii=False, allow_nan=False,
                         separators=(',', ':')).encode('utf-8')
        _require(len(raw) < MAX_BYTES, 'rack project exceeds portable JSON byte bound')
    except ContractError as exc:
        raise ProjectError(str(exc)) from exc


def prepare_revision(project, recipe, record, version):
    """Validate a candidate container without changing the live head or presets."""
    validate_revision(project, recipe, record['parent'])
    candidate = project._blank()
    candidate._revisions = {**project._revisions, record['id']: record}
    candidate._head = record['id']
    candidate._slots = project._slots
    candidate._rack_presets = project._rack_presets
    candidate._format_version = version
    validate_presets(candidate)
    bounded_document(candidate.to_document())


def _install_presets(project, presets):
    candidate = project._blank()
    candidate._revisions = project._revisions
    candidate._head = project._head
    candidate._slots = project._slots
    candidate._format_version = FORMAT_VERSION
    candidate._rack_presets = presets
    validate_presets(candidate)
    bounded_document(candidate.to_document())
    project._rack_presets = presets
    project._format_version = FORMAT_VERSION


def save_preset(project, identifier, name, rack=None, *, replace=False):
    """Save named user data. Never writes the approved source recipe/catalogue."""
    _id(identifier); _name(name)
    _require(type(replace) is bool, 'replace must be boolean')
    _require(replace or identifier not in project._rack_presets,
             'rack preset already exists; explicit replace=True required')
    saved = project.rack if rack is None else rack
    _require(saved is not None, 'no working-copy rack to save')
    saved = saved if isinstance(saved, RackRecipe) else RackRecipe(saved)
    saved.require_source(project.head_recipe)
    origin_id, _ = source_ancestor(project, saved)
    entry = {'id': identifier, 'name': name, 'rack': saved.to_dict(),
             'source_revision_id': origin_id, 'rack_sha256': saved.sha256,
             'sonic_sha256': saved.sonic_sha256}
    presets = deepcopy(project._rack_presets)
    presets[identifier] = entry
    _install_presets(project, presets)
    return deepcopy(entry)


def read_preset(project, identifier):
    _id(identifier)
    _require(identifier in project._rack_presets, 'unknown user rack preset')
    return deepcopy(project._rack_presets[identifier])


def rename_preset(project, identifier, name):
    _name(name)
    read_preset(project, identifier)
    presets = deepcopy(project._rack_presets)
    presets[identifier]['name'] = name
    _install_presets(project, presets)


def apply_preset(project, identifier):
    rack = RackRecipe(read_preset(project, identifier)['rack'])
    # with_rack enforces the existing source identity; no source parameter edits.
    return project.commit(with_rack(project.head_recipe, rack))


def restore_source_and_rack(project, identifier=None):
    """Explicit whole-source recall, distinct from processing-only reset.

    No identifier restores the current rack's no-rack origin. An identifier
    recalls that named preset together with its retained original source.
    """
    if identifier is None:
        _require(project.rack is not None, 'no rack source origin to restore')
        _, source = source_ancestor(project, project.rack)
        return project.commit(source)
    entry = read_preset(project, identifier)
    source = Contract.from_json(project._revisions[entry['source_revision_id']]['recipe_json'])
    return project.commit(with_rack(source, entry['rack']))
