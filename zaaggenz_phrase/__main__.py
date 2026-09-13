"""Create role plans, export them to the ZG-009 timeline, or render generated-source audio."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from . import PhraseRolePlan, template_1234_5555, plan_to_timeline, compile_role_recipe


def load(path):
    return PhraseRolePlan.from_json(path.read_text(encoding='utf-8'))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    template = sub.add_parser('template')
    template.add_argument('output', type=Path)
    template.add_argument('--placement-seed', default='0')
    template.add_argument('--content-seed', default='0')
    timeline = sub.add_parser('timeline')
    timeline.add_argument('plan', type=Path)
    timeline.add_argument('output', type=Path)
    timeline.add_argument('--sample-rate', type=int, default=48000)
    render = sub.add_parser('render')
    render.add_argument('plan', type=Path)
    render.add_argument('output', type=Path)
    render.add_argument('--sample-rate', type=int, default=48000)
    args = parser.parse_args()
    try:
        if args.command == 'template':
            plan = template_1234_5555(placement_seed=args.placement_seed, content_seed=args.content_seed)
            write_json(args.output, plan.to_dict())
            print(json.dumps({'plan_sha256': plan.sha256, 'path': str(args.output)}))
            return
        plan = load(args.plan)
        if args.command == 'timeline':
            document, expansion = plan_to_timeline(plan, sample_rate=args.sample_rate)
            write_json(args.output, document.to_dict())
            print(json.dumps({'plan_sha256': plan.sha256, 'expansion_sha256': expansion.sha256,
                              'revision_id': document.revision_id, 'path': str(args.output)}))
            return
        from scipy.io import wavfile
        from zaaggenz_melody import render_phrase
        bundle = compile_role_recipe(plan, sample_rate=args.sample_rate)
        result = render_phrase(bundle.recipe)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        wavfile.write(args.output, args.sample_rate, result.mix)
        print(json.dumps({'plan_sha256': plan.sha256, 'expansion_sha256': bundle.expansion.sha256,
                          'samples': len(result.mix), 'path': str(args.output)}))
    except KeyboardInterrupt:
        parser.exit(130, 'zaaggenz-phrase: cancelled\n')
    except (ValueError, OSError) as exc:
        parser.exit(2, f'zaaggenz-phrase: {exc}\n')


if __name__ == '__main__':
    main()
