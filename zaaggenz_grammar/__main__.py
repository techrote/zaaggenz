"""Create/reopen exact grammar recipes and render source-derived audio offline."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from . import (GrammarSpec, ExpansionRequest, starter_grammars, make_grammar_recipe,
               save_grammar_recipe, load_grammar_recipe, submit_grammar_render)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('create')
    create.add_argument('output', type=Path)
    create.add_argument('--grammar', choices=tuple(starter_grammars()), default='step-return')
    create.add_argument('--grammar-file', type=Path)
    create.add_argument('--events', type=int, default=32)
    create.add_argument('--step', default='1/2')
    create.add_argument('--seed', default='0')
    create.add_argument('--sample-rate', type=int, default=48000)
    create.add_argument('--bpm', type=float, default=200.)
    render = sub.add_parser('render')
    render.add_argument('recipe', type=Path)
    render.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        if args.command == 'create':
            from zaaggenz_contracts.legacy import adapt_parameters, freeze_legacy
            from uptempo_harmony.synth import PRESETS
            params = adapt_parameters('synth', {**PRESETS['locked_bloom'].to_dict(),
                                               'sr': args.sample_rate, 'bpm': args.bpm, 'beats': 1})
            base = freeze_legacy(params).to_dict()
            grammar = (GrammarSpec.from_json(args.grammar_file.read_bytes()) if args.grammar_file
                       else starter_grammars()[args.grammar])
            request = ExpansionRequest(event_count=args.events, step_beats=args.step, seed=args.seed)
            recipe = make_grammar_recipe(grammar, request, params, base['time_map'], base['tuning'],
                                         quality='standard', tail_mode='truncate')
            save_grammar_recipe(recipe, args.output)
            print(json.dumps({'recipe_sha256': recipe.sha256, 'path': str(args.output)}))
        else:
            from scipy.io import wavfile
            import numpy as np
            from zaaggenz_jobs import JobScheduler, JobError
            recipe = load_grammar_recipe(args.recipe)
            scheduler = JobScheduler()
            try:
                job = submit_grammar_render(recipe, scheduler)
                snapshot = scheduler.wait(job)
                if snapshot.state != 'completed':
                    raise ValueError(snapshot.error or snapshot.state)
                result = scheduler.result(job)
                audio = np.frombuffer(result.audio_bytes, dtype='<f4')
                args.output.parent.mkdir(parents=True, exist_ok=True)
                wavfile.write(args.output, result.asset['sample_rate_hz'], audio)
                print(json.dumps({'recipe_sha256': recipe.sha256, 'samples': len(audio), 'path': str(args.output)}))
            except JobError as exc:
                raise ValueError(str(exc)) from exc
            finally:
                scheduler.shutdown(cancel=True)
    except KeyboardInterrupt:
        parser.exit(130, 'zaaggenz-grammar: cancelled\n')
    except (ValueError, OSError) as exc:
        parser.exit(2, f'zaaggenz-grammar: {exc}\n')


if __name__ == '__main__':
    main()
