# ADR-0007: Exact pgvector search scoped to one patient, with no ANN index

- **Status:** accepted (schema in place; the retriever comes with the records feature)
- **Context:** Records Q&A always searches one patient's documents: tens to hundreds of chunks, never the whole collection. Search across patients is not a feature; it would be a risk.
- **Options:**
  1. *A dedicated vector database.* One more system and one more store of clinical data, and patient scoping has to be re-proven outside Postgres.
  2. *pgvector with an HNSW index.* Approximate, and with a selective filter (one patient) it can return fewer than k results.
  3. *pgvector exact distance after a B-tree filter on `doc_chunk.patient_id`.* Exact results, sub-10 ms at per-patient sizes, and the same table carries RLS (ADR-0003).
- **Decision:** Option 3. `doc_chunk.patient_id` is denormalised from `document` so the filter and RLS need no join. A `tsvector` column and GIN index support hybrid lexical + vector retrieval: lab reports are full of exact tokens (HbA1c, LDL) that embeddings blur. Embeddings come from a self-hosted 1,024-dim multilingual model, so clinical text never leaves the boundary.
- **Revisit trigger:** a single patient's chunk count reaches tens of thousands, or a cross-patient feature is approved.
- **Consequences:**
  - *Easier:* exact results, one database, scoping already proven.
  - *Harder:* no fast path if the access pattern changes; storing two representations (vector and tsvector).
- **Checked on:** 2026-11-02
