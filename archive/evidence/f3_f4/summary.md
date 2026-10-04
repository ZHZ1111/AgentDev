# F3/F4 experiment

Eight small tasks; one stochastic sample each. Coverage is not correctness. Credited mode costs share one physical seed. This is a small known-defect experiment, not a complete mutation system.

| Mode | Passing tasks | Mean line | Mean branch | Coverage unavailable | Branch N/A | Defects detected/evaluable | Credited HTTP |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 5/8 | 100.0 | 100.0 | 2 | 1 | 2/3 | 11 |
| feedback | 5/8 | 100.0 | 100.0 | 2 | 1 | 4/5 | 11 |

| Mode | Credited prompt/completion/total tokens | Seconds including shared seed |
|---|---|---:|
| baseline | None/None/None | 106.791 |
| feedback | None/None/None | 107.604 |

Physical cost (shared seed counted once): {"http_attempts": 11, "actual_network_http_attempts": 11, "token_usage": null}

Missing measurements are null/None, never zero; branch N/A is excluded from the branch mean. Split aggregates are in summary.json.

| Case | Split | Baseline status/line/branch | Feedback status/line/branch | Change |
|---|---|---|---|---|
| order | development | completed / 100.0 / 100.0 | completed / 100.0 / 100.0 | no_coverage_change |
| labels | development | completed / 100.0 / 100.0 | completed / 100.0 / 100.0 | no_coverage_change |
| independent | development | failed / None / None | failed / None / None | no_coverage_change |
| mean | development | completed / 100.0 / 100.0 | completed / 100.0 / 100.0 | no_coverage_change |
| score | holdout | completed / 100.0 / 100.0 | completed / 100.0 / 100.0 | no_coverage_change |
| initials | holdout | needs_review / 100.0 / None | needs_review / 100.0 / None | no_coverage_change |
| rotation | holdout | failed / None / None | failed / None / None | no_coverage_change |
| packet | holdout | completed / 100.0 / 100.0 | completed / 100.0 / 100.0 | no_coverage_change |

| Variant | Mode | Outcome | Attributed failing test |
|---|---|---|---|
| quantity_accepts_zero | baseline | unattributed_failure |  |
| order_quantity_increment | baseline | detected | test_order_total_normal |
| quantity_accepts_zero | feedback | unattributed_failure |  |
| order_quantity_increment | feedback | detected | test_order_total_normal |
| labels_keep_case | baseline | not_evaluable |  |
| labels_keep_case | feedback | detected | test_unit_normalize_mixed, test_unit_normalize_cjk, test_unit_format_normal, test_collab_format_through_normalize |
| mean_empty_division | baseline | not_evaluable |  |
| mean_empty_division | feedback | detected | test_boundary_empty_list, test_branch_empty_falsy_taken |
| score_excludes_80 | baseline | detected | test_boundary_high_edges[80-high] |
| score_excludes_80 | feedback | detected | test_boundary_high_edges[80-high] |
| rotation_wrong_direction | baseline | not_evaluable |  |
| rotation_wrong_direction | feedback | not_evaluable |  |
