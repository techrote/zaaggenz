"""Original synthetic test grammars, not reconstructions of named traditions."""
from .model import GrammarSpec, VERSION


def starter_grammars():
    def build(name, up, down, path):
        return GrammarSpec({
            'format': 'zaaggenz-modal-grammar', 'version': VERSION, 'id': name,
            'description': 'Synthetic five-degree grammar with explicit directional movement and a tonic return.',
            'provenance': {'kind': 'synthetic', 'source': 'Original zaaggenz ZG-011 engineering fixture; no cultural attribution.', 'license': 'CC0-1.0'},
            'period_degrees': 12,
            'degrees': [{'degree': d, 'weight': w} for d, w in ((0, 4), (2, 1), (4, 2), (7, 3), (9, 1))],
            'register': {'minimum': 0, 'maximum': 12},
            'ascending_steps': [{'step': up, 'weight': 4}, {'step': 3, 'weight': 1}],
            'descending_steps': [{'step': -down, 'weight': 4}, {'step': -3, 'weight': 1}],
            'resting_degrees': [0, 7], 'boundary': 'reflect',
            'motifs': [
                {'id': 'rise', 'kind': 'motif', 'direction': 'up', 'steps': [0, 1, 2], 'weight': 1},
                {'id': 'fall', 'kind': 'motif', 'direction': 'down', 'steps': [0, -1, -2], 'weight': 1},
                {'id': 'upper-neighbour', 'kind': 'ornament', 'direction': 'any', 'steps': [0, 1, 0], 'weight': 1},
                {'id': 'lower-neighbour', 'kind': 'ornament', 'direction': 'any', 'steps': [0, -1, 0], 'weight': 1}],
            'return_path': path})
    return {'step-return': build('synthetic-step-return', 1, 2, [4, 2, 0]),
            'skip-return': build('synthetic-skip-return', 2, 1, [9, 7, 0])}
