"""Fail-closed, path-and-value-bound migrations for frozen inverse validation evidence."""
from __future__ import annotations

import copy
import re

SHA256_RE = re.compile(r'^[0-9a-f]{64}$')
VALIDATION_PATH_RE = re.compile(
    r'^/fixtures/[0-9]+/candidates/[0-9]+/(?:fit|holdout|whole_signal)/validation/[0-9]+/(?:state|triggered_gates)$')


def validate_validation_transitions(document):
    """Validate exact validation migrations; broad field/path exemptions are forbidden."""
    if document is None:
        return []
    if (type(document) is not dict
            or document.get('kind') != 'InverseFoundationValidationTransitions'
            or document.get('version') != '1.0.0'):
        raise ValueError('invalid inverse validation-transition document')
    rows = document.get('transitions')
    if type(rows) is not list:
        raise ValueError('validation transitions must be a list')
    seen = set()
    out = []
    for index, row in enumerate(rows):
        if type(row) is not dict:
            raise ValueError(f'validation transition {index} must be an object')
        old = row.get('from_implementation_sha256')
        new = row.get('to_implementation_sha256')
        if (not isinstance(old, str) or not SHA256_RE.fullmatch(old)
                or not isinstance(new, str) or not SHA256_RE.fullmatch(new) or old == new):
            raise ValueError(f'validation transition {index} requires distinct lowercase SHA-256 identities')
        if (old, new) in seen:
            raise ValueError(f'duplicate validation transition {old}->{new}')
        seen.add((old, new))
        if type(row.get('issue')) is not int or row['issue'] <= 0:
            raise ValueError(f'validation transition {index} requires issue number')
        if not isinstance(row.get('stable_id'), str) or not re.fullmatch(r'ZG-\d{3}', row['stable_id']):
            raise ValueError(f'validation transition {index} requires stable_id')
        if not isinstance(row.get('reason'), str) or not row['reason'].strip():
            raise ValueError(f'validation transition {index} requires reason')
        changes = row.get('changes')
        if type(changes) is not list or not changes:
            raise ValueError(f'validation transition {index} requires changes')
        paths = set()
        for change_index, change in enumerate(changes):
            if type(change) is not dict or set(change) != {'path', 'from', 'to'}:
                raise ValueError(
                    f'validation transition {index} change {change_index} requires exactly path/from/to')
            path = change['path']
            if not isinstance(path, str) or not VALIDATION_PATH_RE.fullmatch(path):
                raise ValueError(
                    f'validation transition {index} change {change_index} path is outside portable validation state/gates')
            if path in paths:
                raise ValueError(f'validation transition {index} duplicates path {path}')
            paths.add(path)
            before, after = change['from'], change['to']
            if path.endswith('/state'):
                if (before not in ('accepted', 'rejected') or after not in ('accepted', 'rejected')
                        or before == after):
                    raise ValueError(
                        f'validation transition {index} change {change_index} requires distinct accepted/rejected states')
            else:
                for label, value in (('from', before), ('to', after)):
                    if (type(value) is not list
                            or any(not isinstance(gate, str) or not gate for gate in value)
                            or len(set(value)) != len(value)):
                        raise ValueError(
                            f'validation transition {index} change {change_index} {label} must be a unique gate-name list')
                if before == after:
                    raise ValueError(f'validation transition {index} change {change_index} must change gate list')
        out.append(row)
    return out


def _value(root, path):
    value = root
    for token in path.split('/')[1:]:
        if type(value) is list:
            if not token.isdigit() or int(token) >= len(value):
                raise KeyError(path)
            value = value[int(token)]
        elif type(value) is dict and token in value:
            value = value[token]
        else:
            raise KeyError(path)
    return value


def _set_value(root, path, value):
    tokens = path.split('/')[1:]
    parent = root
    for token in tokens[:-1]:
        parent = parent[int(token)] if type(parent) is list else parent[token]
    last = tokens[-1]
    if type(parent) is list:
        parent[int(last)] = value
    else:
        parent[last] = value


def apply_validation_transition(actual_projection, expected_projection, *, expected_impl, actual_impl,
                                transitions=(), implementation_transition_reviewed=False):
    """Align only exact reviewed validation deltas in a disposable comparison copy."""
    row = next((item for item in transitions
                if item['from_implementation_sha256'] == expected_impl
                and item['to_implementation_sha256'] == actual_impl), None)
    if row is None:
        return actual_projection, [], 0
    failures = []
    if not implementation_transition_reviewed:
        failures.append('/validation-transition: implementation transition is not independently reviewed')
    aligned = copy.deepcopy(actual_projection)
    accepted = 0
    for change in row['changes']:
        path = change['path']
        try:
            predecessor = _value(expected_projection, path)
            successor = _value(aligned, path)
        except (KeyError, IndexError, ValueError, TypeError):
            failures.append(path + ': reviewed transition path does not resolve')
            continue
        if predecessor != change['from']:
            failures.append(path + ': reviewed transition predecessor value mismatch')
            continue
        if successor != change['to']:
            failures.append(path + ': reviewed transition successor value mismatch')
            continue
        _set_value(aligned, path, copy.deepcopy(change['from']))
        accepted += 1
    return aligned, failures, accepted
