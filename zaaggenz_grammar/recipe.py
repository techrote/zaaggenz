"""Explicit authoring wrapper; frozen RenderRecipe/Project v1 are not migrated."""
from __future__ import annotations
import json
import os
from pathlib import Path
import tempfile
from dataclasses import dataclass
from zaaggenz_contracts import Contract, digest
from zaaggenz_contracts.model import loads, check_json
from zaaggenz_melody import make_melodic_recipe, NoteMode
from zaaggenz_project import Project
from .model import GrammarError, GrammarSpec, ExpansionRequest, fields, VERSION
from .expand import expand_grammar


@dataclass(frozen=True, init=False)
class GrammarRecipe:
    """Immutable generator + ordinary project, verified by deterministic re-expansion."""
    _json: str

    def __init__(self, document):
        try:
            check_json(document)
        except ValueError as exc:
            raise GrammarError('grammar recipe exceeds frozen JSON bounds: ' + str(exc)) from exc
        fields(document, {'format', 'version', 'grammar', 'request', 'project', 'expansion_sha256'}, 'grammar recipe')
        if document['format'] != 'zaaggenz-grammar-recipe' or document['version'] != VERSION:
            raise GrammarError('unsupported grammar recipe format/version')
        grammar = GrammarSpec(document['grammar'])
        request = ExpansionRequest.from_dict(document['request'])
        project = Project.from_document(document['project'])
        recipe = project.head_recipe.to_dict()
        if recipe['phrase'] is None:
            raise GrammarError('grammar recipe requires a phrase')
        expansion = expand_grammar(grammar, request, recipe['tuning'], manual_phrase=Contract(recipe['phrase']))
        if expansion.phrase.to_dict() != recipe['phrase'] or expansion.sha256 != document['expansion_sha256']:
            raise GrammarError('grammar/request/expanded phrase identity mismatch')
        object.__setattr__(self, '_json', json.dumps(document, allow_nan=False, sort_keys=True, separators=(',', ':')))

    def to_dict(self):
        return loads(self._json)

    @property
    def project(self):
        return Project.from_document(self.to_dict()['project'])

    @property
    def render_recipe(self):
        return self.project.head_recipe

    @property
    def sha256(self):
        return digest(self.to_dict())

    @classmethod
    def from_json(cls, text):
        return cls(loads(text))


def make_grammar_recipe(grammar, request, synth_params, time_map, tuning, *, manual_phrase=None, **render_options):
    expansion = expand_grammar(grammar, request, tuning, manual_phrase=manual_phrase)
    recipe = make_melodic_recipe(synth_params, time_map, tuning, expansion.phrase,
                                mode=NoteMode.SOURCE_DERIVED, **render_options)
    return GrammarRecipe({'format': 'zaaggenz-grammar-recipe', 'version': VERSION,
                          'grammar': grammar.to_dict(), 'request': request.to_dict(),
                          'project': Project(recipe).to_document(), 'expansion_sha256': expansion.sha256})


def save_grammar_recipe(recipe, path):
    if not isinstance(recipe, GrammarRecipe):
        raise GrammarError('GrammarRecipe required')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as out:
            out.write(recipe._json + '\n')
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def load_grammar_recipe(path):
    with Path(path).open('rb') as stream:
        return GrammarRecipe.from_json(stream.read(2_000_001))
