# corpus/

Holds the labeled reference pattern corpus (`Dataset_and_Evaluation_Spec.md`)
and the evaluation harness (`corpus/eval/` — see `corpus/eval/README.md`)
that the Retrieval Service and Risk Engine depend on.

**The reference pattern corpus (`corpus_patterns`) itself is still empty** —
corpus collection/labeling and the vector index build are later-phase work
(`Implementation_Roadmap.md`). This is a load-bearing fact for interpreting
any evaluation number: with no corpus, dense/lexical retrieval contributes
zero signal in production today (see `corpus/eval/README.md` "What Phase 6
actually found").

The evaluation harness (`corpus/eval/`) is built out as of Phase 6 and does
not wait on the corpus — see `corpus/eval/README.md` for how to run it, its
DEV/TEST/ADVERSARIAL split rules, and its explicit limitations.

Never commit real user-uploaded documents here — only the curated,
version-tagged reference corpus described in `Dataset_and_Evaluation_Spec.md`,
and only synthetic, hand-authored fixtures under `corpus/eval/`.
