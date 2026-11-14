# ScholarPulse: AI-Enabled Academic Knowledge Hub

**Course Project 2026 | Theme 4: Knowledge Hub | Team of 4 (`cs26mt010-tech/scholarpulse`)**

ScholarPulse is a multi-page academic knowledge hub where students upload, search, rate, comment on, and organise course notes, paper summaries, and curated reading lists. Teaching assistants publish official course reading lists, and moderators review reported content with logged actions. To reduce information overload during exam preparation, ScholarPulse includes a grounded **AI Study Assistant**. Retrieval and grounded answers run locally in the backend (deterministic 64-dimension chunk vectors and cosine similarity, no external model), answering only from the text of a chosen resource, a reading list collection (up to 20 resources), or an entire course code (`CS301`, `CS402`, `CS205`, `SE101`) and citing the exact passages used. When nothing relevant is found in the stored documents, an optional server-side fallback asks Google Gemini (`gemini-2.5-flash`) a general-knowledge question and labels the answer as not grounded. Only the question text is sent to Gemini; a MySQL `FULLTEXT` keyword mode is available that never calls Gemini.

## Team Members

| # | Name | Roll No. | Main Area |
| :- | :--- | :--- | :--- |
| 1 | Harshit Pant | `cs26mt006` |Backend: all REST endpoints
(resources, collections, roles and
moderation), upload and chunking,
AI retrieval pipeline |
| 2 | Snehadip Ghoshal | `cs26mt010` | Database (schema, migrations, seed
data), frontend UI/UX for all pages,
accessibility, Figma, Playwright E2E
tests |
| 3 | Gangadevi Venkata Siva krishna | `cs26mt009` | OpenAPI 3.0.3 spec, authentication & security (Argon2id, CSRF), Docker/CI, pytest suite, AI guardrails & evaluation |
| 4 | Ritik Kumar | `cs26mt021` | PPT presentation, integration testing, and evaluation benchmarking |

## Milestones 1–4 Deliverables Included

1. **OpenAPI 3.0.3 YAML Specification (`docs/openapi.yaml`, mirrored at the repository root)**:
   - Complete contract defining **22 REST API paths** and **30 component schemas** across 9 functional tags (`System`, `Auth`, `Users`, `Categories`, `Resources`, `Ratings & Comments`, `Collections`, `AI Study Assistant`, `Moderation`), plus `SessionCookie` (`sp_session`) and `CsrfToken` (`X-CSRF-Token`) security schemes.
2. **Database Schema & Alembic Migrations (`backend/app/models/schema.py` & `backend/alembic/versions/0001_initial_schema_12_tables.py`)**:
   - All **12 relational tables**: `users`, `categories`, `resources`, `resource_chunks`, `tags`, `resource_tags`, `ratings`, `comments`, `collections`, `collection_items`, `reports`, and `ai_queries`.
   - Includes B+Tree composite indexes (`ix_resources_cat_status_rating`, `ix_collection_items_order`, etc.) and MySQL 8 InnoDB `FULLTEXT` indexes (`ft_resource_chunks_text`, `ft_resources_title_content`).
3. **Committed Dataset Subset & 30 Team-Written Course Notes (`data/seed/` & `scripts/build_dataset.py`)**:
   - `data/seed/arxiv_subset.jsonl`: **600 Computer Science paper summaries** sampled deterministically (`SEED=2026`) from the Cornell University arXiv Metadata Dataset (CC0 1.0 Public Domain, <https://www.kaggle.com/datasets/Cornell-University/arxiv>) mapped to `CS301`, `CS402`, `CS205`, and `SE101`.
   - `data/seed/team_notes.jsonl` & `data/seed/notes/*.txt`: **30 original multi-page course notes** (including 3 adversarial prompt-injection test notes) split into ~800-character chunks with 100-character overlap.
   - `data/eval/evaluation_questions.json`: **42 ground-truth evaluation questions** (single-passage, multi-chunk, paraphrased, multi-document, unanswerable refusal, and prompt-injection resilience).
4. **Deterministic, Idempotent Seed Script (`scripts/seed_db.py`)**:
   - Populates **630 resources** (600 arXiv + 30 notes), **1,313 chunks** with embeddings, **20 users** (with salted Argon2id password hashes), **4 course categories**, **66 tags** (`2,515` tag mappings), **800 ratings**, **300 comments**, **15 collections** (`73` items), **6 moderation reports**, and sample audited `ai_queries`.
5. **Single-Command Docker Compose Stack (`docker-compose.yml` & `backend/Dockerfile`)**:
   - Starts `db` (MySQL 8.0 with UTF8MB4 and `mysqladmin ping` healthcheck) and `backend` (FastAPI on port `8000` running `alembic upgrade head` and `scripts/seed_db.py` automatically on startup).

## Quick Start (`docker compose up`)

```bash
# 1. Copy environment variables template (works out of the box with no external download)
cp .env.example .env

# 2. Build and start MySQL 8.0 + FastAPI Backend (auto-runs migrations and seed script)
docker compose up --build

# 3. Verify stack health and seeded table counts
curl http://localhost:8000/api/v1/health
```

- **Web UI** (wired to the live API): `http://localhost:8000/`
- **Endpoint reference**: [`docs/API_ENDPOINTS.md`](docs/API_ENDPOINTS.md)
- **Interactive Swagger UI (OpenAPI)**: `http://localhost:8000/docs`
- **Raw OpenAPI 3.0.3 YAML**: `http://localhost:8000/api/v1/openapi.yaml`

## Running Tests, Coverage & Browser Checks

```bash
# Backend integration tests with the MS-4 minimum coverage gate (60%)
pytest backend/tests/test_ms3_stack.py --cov=app --cov-report=term-missing --cov-fail-under=60

# RAG & guardrail evaluation benchmark
python scripts/evaluate_rag.py

# Browser smoke tests (from frontend/)
cd frontend
npm install
npx playwright install chromium
npm test
```


## Milestone 2 and 3 implementation guide

See [`docs/MS2_MS3_IMPLEMENTATION.md`](docs/MS2_MS3_IMPLEMENTATION.md) for the clickable-prototype-to-endpoint mapping, 12-table ER model, authentication/CSRF conventions, setup commands, seeded demo accounts, scope notes and submission checklist.


## MS-4 CI verification

GitHub Actions runs Python compilation, Ruff, OpenAPI validation, Alembic migrations,
idempotent database seeding, Pytest with a **60% minimum coverage gate**, the RAG
evaluation benchmark, and Playwright browser smoke tests. The workflow uploads coverage
and Playwright reports as artifacts.

A passing local test run or a workflow file does not by itself prove that GitHub Actions
has passed on the remote repository. Check the Actions tab after pushing these changes.

## Milestone evidence still requiring team/GitHub action

- Attach the actual Figma prototype export and record the prototype URL/version.
- Complete and record manual keyboard, focus-visible, and WCAG contrast checks; do not
  mark accessibility as passed without measuring the actual rendered interface.
- Link at least one reviewed/approved pull request per the team's review requirement.


## Ask AI: Gemini fallback when data is not found

`POST /api/v1/ai/ask` first searches the stored documents (resource, collection or course scope). If nothing relevant is found **and** `GEMINI_API_KEY` is set in `.env`, the backend asks Google Gemini (`GEMINI_GENERATION_MODEL`, default `gemini-2.5-flash`) and returns:

- `general_ai_used: true`, `not_found: false`, empty `citations`, and a `general_ai_notice` saying the answer is not grounded in ScholarPulse documents (the UI shows it in a separate blue "Gemini - General Answer" box).
- Without a key, on a Gemini error/quota/timeout, or when "Keyword search only" is ticked, the usual "Not found in this document" refusal is returned. Only the question text is sent to Gemini (no document text, emails or other identifiers).

The key stays server-side. Get one at https://aistudio.google.com/apikey, then set `GEMINI_API_KEY=...` in `.env` and restart (`docker compose up --build`).
