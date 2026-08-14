# Legal Document Comparison

You can compare an **outside legal document** (something the user has — a
checklist, a draft, a letter) against **our legal corpus** (the
`legal-docs/` mirror of the protocol docs repository). Access is read-only and
staff-only: you may read and compare, never modify, push, or submit.

## When to use this skill

Use it when the user wants to compare a document they have with what we have:

- "I have this business registration checklist — compare it to our docs."
- "How does this draft differ from ours?"
- "Is this the same as what's in the repo?"

Do NOT use it for plain legal questions with no outside document (use the
Lexor informational tools directly), or for general chat.

## Step 1 — Assemble the outside document

The document arrives one of two ways:

1. **Pasted text** (Discord DMs, possibly across several messages). Gather the
   document text from the recent conversation. If it looks truncated or you
   cannot tell where it ends, ask: *"Is that the whole document, or is there
   more?"* Do not compare until the user confirms it is complete.
2. **A file on the local machine**, named by the user (e.g.
   `inbox/checklist.md`). Read it with a `local_tool` step:
   `{"name": "file_read", "path": "inbox/<filename>"}`.

Text and markdown only. If the user has a PDF or other binary format, reply:
*"I can't read that file format yet. Reason: only text/markdown documents are
supported right now. To proceed: open the PDF, copy the text, and paste it
here (or save it as a .txt/.md file in the inbox folder)."*

## Step 2 — Refresh the local corpus

Run a `local_tool` step: `{"name": "docs_sync"}`.

- If the output reports a block or skip (staff-only, no credential), relay the
  message to the user verbatim and stop.
- If it reports a staleness warning, continue, but mention in your final
  summary that the local copy may lag the latest corpus.

## Step 3 — Find the matching corpus documents

Run a `lexor_call` step with `search.semantic` to find what our corpus says
about the subject:

```json
{"tool": "search.semantic", "params": {"query": "<subject of the outside document>", "top_k": 8}}
```

Each hit carries a `file_path`. That path is relative to the corpus root, so
the local copy lives at `legal-docs/<file_path>`. Pick the 1–3 most relevant
distinct documents. If Lexor is unavailable, fall back to asking the user
which area applies and listing likely folders under `legal-docs/01_corpus/`.

## Step 4 — Read the candidates

For each chosen candidate, run a `local_tool` step:
`{"name": "file_read", "path": "legal-docs/<file_path>"}`.

If a file is missing locally, say so and drop it from the comparison — never
invent its content.

## Step 5 — Compare

Two modes:

- **Same-document variant** (the outside document is clearly a copy of one
  corpus file, edited or older): run a `local_tool` step
  `{"name": "text_diff", "path_a": "<saved outside doc path>", "path_b": "legal-docs/<file_path>"}`
  and summarize the exact changes. (Save the pasted outside text first with
  `file_append_markdown` to `inbox/outside-<slug>.md` so both files exist.)
- **Different-format document** (the usual case — e.g. a state checklist vs
  our internal docs): produce a **gap analysis** with these sections:
  - **Covered** — items present in both, with the corpus path that covers them.
  - **Missing from ours** — items in their document that our corpus lacks.
  - **Extra in ours** — items we require that their document omits.
  - **Conflicts** — requirements that disagree, quoting both sides.
  Every point must cite a real corpus path you actually read. If nothing in
  the corpus matches, say: "I found no matching document in the corpus" — do
  not fabricate citations.

## Step 6 — Report

Save the full report with `file_append_markdown` to
`reports/compare-<slug>-<date>.md`, then answer the user with:

1. A short summary of the most important gaps/conflicts.
2. The corpus paths consulted.
3. The saved report path.

## Rules

- Read-only, always. Never modify anything under `legal-docs/`, never push,
  never attempt Lexor write/draft tools.
- Quote at most short excerpts from corpus documents in your reply — summaries
  and citations, not full-text dumps.
- Relay every block/warning message (staff-only, staleness, Lexor down) to the
  user verbatim; never silently drop corpus context. If you compared without
  Lexor guidance, say so.
