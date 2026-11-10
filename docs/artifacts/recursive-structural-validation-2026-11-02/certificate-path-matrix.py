from __future__ import annotations
import copy, hashlib, importlib.util, json, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from tools.recursive_necessity_baselines import StructuralRivals
ENVS = (
    'recursive_gluing', 'recursive_gluing_discovery', 'recursive_maze_gluing',
    'recursive_distributed_gluing', 'recursive_epistemic_gluing',
    'recursive_compiler_bootstrap', 'recursive_error_correcting_codes',
    'recursive_coarse_graining',
)
def check(net, env, instance, candidate):
    try:
        if env == 'recursive_gluing':
            parsed, reason = net.parse_solve_output(instance, candidate)
            valid = parsed is not None
            if valid and parsed['status'] == 'unsat':
                valid = not net.oracle_satisfiable(instance)
            return bool(valid), reason
        return net.verify_certificate(instance, candidate)
    except Exception as exc:
        return False, type(exc).__name__ + ': ' + str(exc)
runner = StructuralRivals()
out = {'schema_version': 1, 'seed': 41, 'depth': 2, 'environments': {}}
for env in ENVS:
    net, public_fn, items, strategies = runner.configure(env, 2, 41)
    rows = []
    for name, instance in items:
        public = public_fn(instance) if public_fn is not None else copy.deepcopy(instance)
        reference = strategies[0][2](copy.deepcopy(public))
        second = strategies[0][2](copy.deepcopy(public))
        positive, positive_reason = check(net, env, instance, reference)
        malformed = []
        for label, value in (
            ('null', None), ('empty_object', {}), ('missing_status', {'reference_acc': 1.0}),
            ('sat_without_certificate', {'status': 'sat', 'reference_acc': 1.0}),
        ):
            accepted, reason = check(net, env, instance, value)
            malformed.append({'case': label, 'accepted': bool(accepted), 'reason': str(reason)})
        if isinstance(reference, dict) and reference.get('status') == 'sat':
            wrong = copy.deepcopy(reference)
            wrong['status'] = 'unsat'
        else:
            wrong = {'status': 'sat', 'reference_acc': 1.0}
        wrong_ok, wrong_reason = check(net, env, instance, wrong)
        rows.append({
            'check': name, 'positive_accepted': positive, 'positive_reason': str(positive_reason),
            'deterministic_reference': reference == second,
            'wrong_status_accepted': bool(wrong_ok), 'wrong_status_reason': str(wrong_reason),
            'malformed': malformed,
        })
    out['environments'][env] = {
        'checks': len(rows), 'positive_all_accepted': all(r['positive_accepted'] for r in rows),
        'deterministic_all': all(r['deterministic_reference'] for r in rows),
        'wrong_status_all_rejected': all(not r['wrong_status_accepted'] for r in rows),
        'malformed_all_rejected': all(not m['accepted'] for r in rows for m in r['malformed']),
        'rows': rows,
    }
Path('docs/artifacts/recursive-structural-validation-2026-11-02/certificate-path-matrix.json').write_text(json.dumps(out, indent=2) + '\n')
print(json.dumps({e: {k:v for k,v in row.items() if k != 'rows'} for e,row in out['environments'].items()}, indent=2))
