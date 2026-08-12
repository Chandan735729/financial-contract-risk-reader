# corpus/

Holds the labeled reference pattern corpus (`Dataset_and_Evaluation_Spec.md`)
and the evaluation harness (`corpus/eval/`, `Implementation_Roadmap.md` Phase
7) that the Retrieval Service and Risk Engine depend on.

Empty in Phase 0 — corpus collection/labeling and the vector index build are
later-phase work (`Implementation_Roadmap.md`). This placeholder exists so
the directory is tracked by git ahead of that work.

Never commit real user-uploaded documents here — only the curated,
version-tagged reference corpus described in `Dataset_and_Evaluation_Spec.md`.
