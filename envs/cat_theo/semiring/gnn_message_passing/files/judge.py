#!/usr/bin/env python3
"""Judge for gnn_message_passing environment."""
import os
import sys
import torch

from judge_lib import (base_result, emit, eval_env, judge_event, make_workdir,
                       mark_check, run, score_from_accuracy, scrub_workdir,
                       set_failure, set_metric, train_env, validate_submission,
                       require_changed_files)

PASS_THRESHOLD = %%SCORING_PASS_THRESHOLD%%
PARTIAL_THRESHOLD = %%SCORING_PARTIAL_THRESHOLD%%

def main() -> None:
    result = base_result(training_completed=False, model_saved=False, accuracy_bin="0%")
    patched_dir = validate_submission(result)
    require_changed_files(result, {"gnn.py"})
    workdir, original_files = make_workdir(patched_dir)

    eval_script = os.path.join(workdir, "_eval_runner.py")
    with open(eval_script, "w", encoding="utf-8") as f:
        f.write(f"""
import sys, torch
sys.path.insert(0, {workdir!r})
from gnn import %%MODEL_CLASS%%

layer = %%MODEL_CLASS%%(in_features=8, out_features=8)
layer.eval()

checks = {{}}

# 1. Output shape correctness
try:
    adj = torch.eye(4)
    x = torch.randn(4, 8)
    out = layer(adj, x)
    checks["basic_run"] = bool(out.shape == x.shape)
except Exception:
    checks["basic_run"] = False

# 2. Strict Permutation Equivariance (The Graph Functorial Property)
try:
    N = 6
    adj = torch.zeros(N, N)
    # A simple path graph (0-1-2-3-4-5)
    for i in range(N - 1):
        adj[i, i+1] = 1.0
        adj[i+1, i] = 1.0
        
    x = torch.arange(1, N * 8 + 1, dtype=torch.float).reshape(N, 8)
    
    # Generate a random permutation matrix P
    p_indices = torch.randperm(N)
    P = torch.zeros(N, N)
    for i, idx in enumerate(p_indices.tolist()):
        P[i, idx] = 1.0
        
    # Permute adjacency and node features
    perm_adj = torch.matmul(torch.matmul(P, adj), P.transpose(0, 1))
    perm_x = torch.matmul(P, x)
    
    # Path A: transform permuted input
    out_perm_input = layer(perm_adj, perm_x)
    
    # Path B: permute original output
    perm_out_original = torch.matmul(P, layer(adj, x))
    
    # Check if they are identical (commute perfectly)
    checks["permutation_equivariance"] = bool(torch.allclose(out_perm_input, perm_out_original, atol=%%TOLERANCE%%))
except Exception as e:
    checks["permutation_equivariance"] = False

torch.save(checks, "eval_outputs.pt")
""")

    ep = run([sys.executable, eval_script], workdir, 60, eval_env())
    if ep.returncode != 0:
        set_failure(result, "RUNTIME_ERROR", "Verification script failed:\n" + ep.stderr[-500:])
        emit(result)

    try:
        checks = torch.load(os.path.join(workdir, "eval_outputs.pt"), weights_only=True)
        basic_ok = bool(checks.get("basic_run", False))
        equiv_ok = bool(checks.get("permutation_equivariance", False))

        mark_check(result, "basic_run", basic_ok)
        mark_check(result, "permutation_equivariance", equiv_ok)

        passed = sum([basic_ok, equiv_ok])
        accuracy = passed / 2.0
        result["training_completed"] = True
        result["model_saved"] = True
        
        score_from_accuracy(result, accuracy, PASS_THRESHOLD, PARTIAL_THRESHOLD, anti_gaming_passed=True)
    except Exception as e:
        set_failure(result, "REWARD_DENIAL", f"Failed to score: {e}")
    
    emit(result)

if __name__ == "__main__":
    main()
