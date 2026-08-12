"""Ground-truth evaluation datasets — Phase 6 spec SS1-2.

Every module here is synthetic and hand-authored (see each module's
docstring and `corpus/eval/README.md`), organized into non-overlapping
`DatasetSplit` groups (`corpus.eval.schema.DatasetSplit`):

- `DEV`: used for threshold/weight tuning (`run_threshold_tuning.py`) and
  ablation analysis. May be inspected freely during development.
- `TEST`: held out, reported only, never used to select a weight or
  threshold. Small — do not over-claim statistical power from it.
- `ADVERSARIAL`: stress cases designed to break naive heuristics (e.g.
  negation, cross-reference, high-similarity-but-safe). Reported
  separately; also never used for tuning.

No real (non-synthetic) financial document text exists anywhere in this
package — see `corpus/eval/README.md` "What this benchmark is not."
"""
