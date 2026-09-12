"""Bounded JSON and immutable contract identity. No audio or network imports."""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import hashlib
import json
import math
import re

MAX_BYTES = 2_000_000
MAX_DEPTH = 32
MAX_NODES = 100_000
SAFE_INT = 2**53 - 1
DOMAIN = b'zaaggenz.contract.c14n-v1\0'
RATIONAL = r'^(0|-?[1-9][0-9]{0,12})/[1-9][0-9]{0,12}$'
SEED = r'^(0|[1-9][0-9]{0,19})$'


class ContractError(ValueError):
    """An invalid/unsupported contract; never silently repaired."""


def check_json(value):
    """Reject non-JSON values, unsafe integers, cycles and resource excess."""
    count = 0
    active = set()

    def visit(x, depth):
        nonlocal count
        count += 1
        if count > MAX_NODES or depth > MAX_DEPTH:
            raise ContractError('JSON exceeds node/depth limit')
        if x is None or type(x) is bool:
            return
        if type(x) is int:
            if abs(x) > SAFE_INT:
                raise ContractError('integer exceeds interoperable safe range; use a declared string')
        elif type(x) is float:
            if not math.isfinite(x) or (x.is_integer() and abs(x) > SAFE_INT):
                raise ContractError('nonfinite/unsafe numeric value')
        elif type(x) is str:
            if len(x) > 65536 or any(0xD800 <= ord(c) <= 0xDFFF for c in x):
                raise ContractError('string exceeds limit or contains an unpaired surrogate')
        elif type(x) in (dict, list):
            if id(x) in active:
                raise ContractError('cyclic JSON input')
            active.add(id(x))
            if type(x) is dict:
                for k, v in x.items():
                    if type(k) is not str:
                        raise ContractError('object keys must be strings')
                    visit(k, depth + 1)
                    visit(v, depth + 1)
            else:
                for v in x:
                    visit(v, depth + 1)
            active.remove(id(x))
        else:
            raise ContractError(f'unsupported JSON value type: {type(x).__name__}')

    visit(value, 0)
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')) > MAX_BYTES:
        raise ContractError('JSON exceeds byte limit')


def loads(text):
    """Strict UTF-8 JSON, including duplicate-key and nonfinite rejection."""
    if not isinstance(text, (str, bytes)):
        raise ContractError('JSON text or UTF-8 bytes required')
    if len(text) > MAX_BYTES:
        raise ContractError('JSON exceeds byte limit')

    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                raise ContractError('duplicate object key: ' + k)
            result[k] = v
        return result

    def bad_constant(_):
        raise ContractError('nonfinite JSON token')

    def integer_token(token):
        if len(token.lstrip('-')) > 16:
            raise ContractError('integer token exceeds interoperable safe range')
        return int(token)

    try:
        if isinstance(text, bytes):
            text = text.decode('utf-8')
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant, parse_int=integer_token)
        check_json(value)
        return value
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise ContractError('invalid or excessively nested JSON') from exc


def fraction(value):
    if type(value) is not str or not re.fullmatch(RATIONAL, value):
        raise ContractError('expected a bounded reduced rational string p/q')
    out = Fraction(value)
    if value != f'{out.numerator}/{out.denominator}':
        raise ContractError('rational must be reduced; zero is 0/1')
    return out


def rational(value):
    """Adapter helper: decimal numeric spelling -> rational, not accumulated steps."""
    try:
        q = Fraction(str(value))
        text = f'{q.numerator}/{q.denominator}'
        fraction(text)
        return text
    except (ValueError, ZeroDivisionError) as exc:
        raise ContractError('value cannot be represented as a bounded rational') from exc


def seed_value(value):
    if type(value) is not str or not re.fullmatch(SEED, value) or int(value) >= 2**64:
        raise ContractError('seed must be a canonical unsigned 64-bit decimal string')
    return int(value)


def derive_seed(root, stream):
    """SHA-256 named stream, first 64 bits big-endian; adding a stream changes no others."""
    seed_value(root)
    if type(stream) is not str or not re.fullmatch(r'[a-z][a-z0-9_.-]{0,63}', stream):
        raise ContractError('invalid stream name')
    material = b'zaaggenz.seed-v1\0' + root.encode('ascii') + b'\0' + stream.encode('ascii')
    return str(int.from_bytes(hashlib.sha256(material).digest()[:8], 'big'))


def canonical_bytes(value):
    """Tagged, exact-binary-rational numbers. Deliberately NOT RFC 8785/JCS."""
    check_json(value)

    def tagged(x):
        if x is None:
            return ['null']
        if type(x) is bool:
            return ['bool', x]
        if type(x) in (int, float):
            q = Fraction(x)
            return ['number', str(q.numerator), str(q.denominator)]
        if type(x) is str:
            return ['string', x]
        if type(x) is list:
            return ['array', [tagged(v) for v in x]]
        return ['object', [[k, tagged(x[k])] for k in sorted(x)]]

    return DOMAIN + json.dumps(tagged(value), ensure_ascii=False, separators=(',', ':')).encode('utf-8')


def digest(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


@dataclass(frozen=True, init=False)
class Contract:
    """Owns a defensive serialized snapshot; every access returns a fresh copy."""
    _json: bytes

    def __init__(self, data):
        from .validation import validate
        validate(data)
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
        object.__setattr__(self, '_json', raw)

    @classmethod
    def from_json(cls, text):
        return cls(loads(text))

    def to_dict(self):
        return loads(self._json)

    def to_json(self):
        return self._json.decode('utf-8')

    @property
    def sha256(self):
        return digest(self.to_dict())
