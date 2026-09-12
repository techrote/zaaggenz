"""Validate metadata offline, or export standalone JSON Schemas."""
import argparse
import json
from pathlib import Path
from . import Contract, ContractError, KINDS, schema


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    check = sub.add_parser('validate'); check.add_argument('file', type=Path)
    export = sub.add_parser('export'); export.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    try:
        if args.command == 'validate':
            with args.file.open('rb') as f:
                value = Contract.from_json(f.read(2_000_001))
            print(json.dumps({'kind': value.to_dict()['kind'], 'sha256': value.sha256}))
        else:
            args.out.mkdir(parents=True, exist_ok=True)
            for kind in KINDS:
                (args.out / (kind + '.schema.json')).write_text(json.dumps(schema(kind), indent=2) + '\n', encoding='utf-8')
            print('Exported 11 self-contained draft-2020-12 schemas; semantic validation is additionally required.')
    except (ContractError, OSError) as exc:
        p.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
