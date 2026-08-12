"""Evaluation framework — Phase 6 (Dataset_and_Evaluation_Spec.md SS5-SS8,
Implementation_Roadmap.md Phase 5 "Evaluation Harness (Gating Infrastructure)").

`corpus/eval/` is the single place every accuracy claim in this project is
computed and re-checkable. Nothing here should be trusted as a production
accuracy number unless its report explicitly says so — see
`corpus/eval/README.md` for the synthetic-vs-real-world distinction that
applies to every metric produced by this package.
"""
