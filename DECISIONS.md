> Draft decision entries created by implementation assistants remain under
> `DRAFT — REVIEW REQUIRED` until reviewed and rewritten by the project author.

---

# DRAFT — REVIEW REQUIRED

## Upload creates an analysis

**Choice:** Each uploaded fund-universe CSV creates an `analysis` record. Later workflow artifacts—mandate settings, calculated metrics, ranking results, evidence, and memo output—are associated with that analysis.

**Why:** An allocator's recommendation is meaningful only in the context of a specific universe, data-quality state, benchmark selection, and mandate. Using one analysis ID gives the workflow a stable audit boundary without introducing a multi-user workspace model.

**Consequence:** V1 treats reruns as new analyses rather than mutating a prior run. A later version could support named scenarios that reuse one source universe with multiple mandates.
