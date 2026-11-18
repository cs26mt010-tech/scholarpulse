# AI Usage Disclosure (`AI_USAGE.md`)

**Project**: ScholarPulse — AI-Enabled Academic Knowledge Hub (`cs26mt010-tech/scholarpulse`)

## 1. Runtime AI Feature in the Application

The AI Study Assistant (`POST /api/v1/ai/ask`) has two parts. They are described separately because only one of them calls an external model.

### 1a. Grounded retrieval and answers (local, no external model)
- Documents are split into ~800-character chunks (100-character overlap). Each chunk gets a 64-dimension vector from `compute_embedding()` in `backend/app/services/rag_service.py`. It is a deterministic, hand-built vector (34 curriculum-concept dimensions plus 30 hashed token dimensions), **not** a Gemini embedding.
- Retrieval is cosine similarity over the chunks in the chosen scope (resource, collection or course). Answers are assembled locally from the retrieved chunks, and every citation is checked against the retrieved set.
- Because this part runs locally, it never sends any data to an external service, needs no API key, and cannot run out of quota.

### 1b. Gemini general-knowledge fallback (the only external model call)
- Used only when nothing relevant is found in the stored documents **and** `GEMINI_API_KEY` is set. Model: `gemini-2.5-flash` via `generateContent`, called server-side from `generate_gemini_general_answer()`.
- **Data sent to Gemini:** the user's question text only (trimmed, at most 300 characters). No document text, usernames, emails, password hashes, session tokens or other identifiers are sent. The API key is sent in an HTTP header from the server and never reaches the browser or the repository.
- The answer is labelled in the UI as "not grounded in ScholarPulse documents", has no citations, and may be inaccurate.

### 1c. Guardrails and failure behaviour
- Question length limit (300 characters), scope validation, and a per-user rate limit (20 questions per hour, `AI_RATE_LIMIT_PER_HOUR`).
- Stored document text is treated as untrusted: known prompt-injection sentences are replaced with `[UNTRUSTED_INSTRUCTION_IGNORED]` before an answer is built, and chunks are wrapped in `<untrusted_document_chunk>` delimiters. The question sent to Gemini is sent as a user message, and the system prompt tells the model not to treat it as instructions.
- Gemini calls use a 10-second timeout and 1 retry on server errors or timeouts. Quota, key or other 4xx errors are not retried. On any Gemini failure the user gets the normal "Not found in this document" answer plus the reason; the rest of the site is unaffected.
- A "Keyword search only" option uses MySQL `FULLTEXT` passage matching and never calls Gemini.
- Tests never call Gemini: the model call is mocked in `backend/tests/test_ms5_auth_ai.py`, and `conftest.py` blanks `GEMINI_API_KEY`.

### 1d. Evaluation (what the numbers mean)
- `scripts/evaluate_rag.py` runs 42 team-written questions (34 answerable, 8 unanswerable) against the **local** pipeline in 1a. It does not exercise Gemini, so its high scores say nothing about Gemini's answer quality. The questions were written by the team over the team's own notes, so they are an optimistic test, not an independent benchmark.
- The Gemini fallback (1b) was checked separately by hand; see the evaluation section of the final report.

## 2. Development-Time AI Assistance
- AI coding assistants were used to help draft boilerplate OpenAPI 3.0.3 schema definitions, SQLAlchemy 2.0 ORM type annotations, and synthetic seed templates.
- Claude (Anthropic) was used during MS-5 to audit the repository against the MS-5 requirements and to draft `backend/tests/test_ms5_auth_ai.py` (auth lifecycle, ownership checks, mocked Gemini tests), one extra Playwright end-to-end test, and the 70% coverage gate in CI. The team ran the tests locally, reviewed the code, and merged it through a reviewed pull request.
- All database schema relationships, role-based access control checks, Argon2id/CSRF security logic, and the 42 evaluation questions were reviewed and verified by the team.

### Example where the assistant's output was wrong
While preparing MS-5, the assistant told us that putting a real `GEMINI_API_KEY` in `.env` and running `python scripts/evaluate_rag.py` would produce a live Gemini evaluation. We checked by reading `rag_service.py`: `compute_embedding()` is a local deterministic function and `generate_gemini_general_answer()` is the only place Gemini is called, and the evaluation script never calls it. The assistant's claim was wrong, and the same mistake was present in our README and this file (they said embeddings and grounded answers used Gemini). We corrected the documentation to describe what the code actually does (sections 1a and 1b above) and report the Gemini fallback evaluation separately.
