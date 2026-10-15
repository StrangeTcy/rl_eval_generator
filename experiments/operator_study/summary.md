# Observational-equivalence operator: offline instrument results

Deterministic procedures on matched generated instances. No model was contacted;
see the claim ceiling in `spec/observational-equivalence-check.yaml`.

## epistemic_fragmented_observation

### identifiable

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 24 | 0.833 | 0.641-0.933 | 0.833 | n/a | n/a | n/a | 0.00 | 0.00 |
| `state_enumeration` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check_literal` | 24 | 0.000 | 0.000-0.138 | 0.000 | n/a | n/a | n/a | 1.00 | 1.00 |
| `equivalence_check_revised` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667
- `equivalence_check`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667
- `equivalence_check_literal`: 24 pairs, arm-only 0, control-only 20, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [-0.9332, -0.597], mean score Δ -0.8333
- `equivalence_check_revised`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667

### pooled

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 24 | 0.833 | 0.641-0.933 | 0.833 | n/a | n/a | n/a | 0.00 | 0.00 |
| `state_enumeration` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check_literal` | 24 | 0.000 | 0.000-0.138 | 0.000 | n/a | n/a | n/a | 1.00 | 1.00 |
| `equivalence_check_revised` | 24 | 1.000 | 0.862-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667
- `equivalence_check`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667
- `equivalence_check_literal`: 24 pairs, arm-only 0, control-only 20, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [-0.9332, -0.597], mean score Δ -0.8333
- `equivalence_check_revised`: 24 pairs, arm-only 4, control-only 0, exact McNemar 0.1250, exact Wilcoxon 0.1250, Newcombe 95% on the arm-minus-control accuracy difference [-0.0037, 0.3585], mean score Δ 0.1667

## epistemic_games

### identifiable

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 96 | 0.042 | 0.016-0.102 | 0.702 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |
| `state_enumeration` | 96 | 1.000 | 0.962-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |
| `equivalence_check` | 96 | 1.000 | 0.962-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |
| `equivalence_check_literal` | 96 | 1.000 | 0.962-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |
| `equivalence_check_revised` | 96 | 1.000 | 0.962-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 96 pairs, arm-only 92, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.8865, 0.9837], mean score Δ 0.2976
- `equivalence_check`: 96 pairs, arm-only 92, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.8865, 0.9837], mean score Δ 0.2976
- `equivalence_check_literal`: 96 pairs, arm-only 92, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.8865, 0.9837], mean score Δ 0.2976
- `equivalence_check_revised`: 96 pairs, arm-only 92, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.8865, 0.9837], mean score Δ 0.2976

### non_identifiable

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 48 | 0.000 | 0.000-0.074 | 0.356 | 1.000 | 0.500 | 0.000 | 0.00 | 0.00 |
| `state_enumeration` | 48 | 0.500 | 0.364-0.636 | 0.500 | 0.000 | 0.500 | 0.000 | 0.00 | 0.00 |
| `equivalence_check` | 48 | 0.500 | 0.364-0.636 | 0.500 | 0.000 | 0.000 | 0.500 | 0.00 | 0.00 |
| `equivalence_check_literal` | 48 | 0.500 | 0.364-0.636 | 0.500 | 0.000 | 0.000 | 0.500 | 0.00 | 0.00 |
| `equivalence_check_revised` | 48 | 1.000 | 0.926-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 48 pairs, arm-only 24, control-only 0, exact McNemar <0.0001, exact Wilcoxon 0.0023, Newcombe 95% on the arm-minus-control accuracy difference [0.345, 0.6361], mean score Δ 0.1437
- `equivalence_check`: 48 pairs, arm-only 24, control-only 0, exact McNemar <0.0001, exact Wilcoxon 0.0023, Newcombe 95% on the arm-minus-control accuracy difference [0.345, 0.6361], mean score Δ 0.1437
- `equivalence_check_literal`: 48 pairs, arm-only 24, control-only 0, exact McNemar <0.0001, exact Wilcoxon 0.0023, Newcombe 95% on the arm-minus-control accuracy difference [0.345, 0.6361], mean score Δ 0.1437
- `equivalence_check_revised`: 48 pairs, arm-only 48, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.8952, 1.0], mean score Δ 0.6438

### pooled

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 144 | 0.028 | 0.011-0.069 | 0.587 | 0.333 | 0.167 | 0.000 | 0.00 | 0.00 |
| `state_enumeration` | 144 | 0.833 | 0.764-0.885 | 0.833 | 0.000 | 0.167 | 0.000 | 0.00 | 0.00 |
| `equivalence_check` | 144 | 0.833 | 0.764-0.885 | 0.833 | 0.000 | 0.000 | 0.167 | 0.00 | 0.00 |
| `equivalence_check_literal` | 144 | 0.833 | 0.764-0.885 | 0.833 | 0.000 | 0.000 | 0.167 | 0.00 | 0.00 |
| `equivalence_check_revised` | 144 | 1.000 | 0.974-1.000 | 1.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 144 pairs, arm-only 116, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.7288, 0.8619], mean score Δ 0.2463
- `equivalence_check`: 144 pairs, arm-only 116, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.7288, 0.8619], mean score Δ 0.2463
- `equivalence_check_literal`: 144 pairs, arm-only 116, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.7288, 0.8619], mean score Δ 0.2463
- `equivalence_check_revised`: 144 pairs, arm-only 140, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.9233, 0.9891], mean score Δ 0.413

## epistemic_nested_knowledge

### identifiable

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 36 | 0.556 | 0.396-0.705 | 0.556 | n/a | n/a | n/a | 0.00 | 0.00 |
| `state_enumeration` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check_literal` | 36 | 0.000 | 0.000-0.096 | 0.000 | n/a | n/a | n/a | 1.00 | 1.00 |
| `equivalence_check_revised` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444
- `equivalence_check`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444
- `equivalence_check_literal`: 36 pairs, arm-only 0, control-only 20, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [-0.7046, -0.369], mean score Δ -0.5556
- `equivalence_check_revised`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444

### pooled

| arm | n | strict accuracy | Wilson 95% | mean score | claims a separation | over-commits | under-commits | answer withheld | format invalid |
|---|---|---|---|---|---|---|---|---|---|
| `control` | 36 | 0.556 | 0.396-0.705 | 0.556 | n/a | n/a | n/a | 0.00 | 0.00 |
| `state_enumeration` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |
| `equivalence_check_literal` | 36 | 0.000 | 0.000-0.096 | 0.000 | n/a | n/a | n/a | 1.00 | 1.00 |
| `equivalence_check_revised` | 36 | 1.000 | 0.904-1.000 | 1.000 | n/a | n/a | n/a | 0.00 | 0.00 |

Matched-pair contrasts against `control` (same instance, both arms):

- `state_enumeration`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444
- `equivalence_check`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444
- `equivalence_check_literal`: 36 pairs, arm-only 0, control-only 20, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [-0.7046, -0.369], mean score Δ -0.5556
- `equivalence_check_revised`: 36 pairs, arm-only 16, control-only 0, exact McNemar <0.0001, exact Wilcoxon <0.0001, Newcombe 95% on the arm-minus-control accuracy difference [0.2669, 0.6042], mean score Δ 0.4444

