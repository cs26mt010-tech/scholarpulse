# ScholarPulse: AI-Enabled Academic Knowledge Hub

**Course Project 2026 | Theme 4: Knowledge Hub | Team of 4 (`cs26mt010-tech/scholarpulse`)**

ScholarPulse is a multi-page academic knowledge hub where students upload, search, rate, comment on, and organise course notes, paper summaries, and curated reading lists. Teaching assistants publish official course reading lists, and moderators review reported content with logged actions. To reduce information overload during exam preparation, ScholarPulse includes a grounded **AI Study Assistant** (Google Gemini API `gemini-embedding-001` and `gemini-2.5-flash`, called strictly server-side) that answers questions using only the text of a chosen resource, a reading list collection (up to 20 resources), or an entire course code (`CS301`, `CS402`, `CS205`, `SE101`), citing the exact passages used and falling back to MySQL `FULLTEXT` keyword search on timeout or quota exhaustion.

## Team Members

| # | Name | Roll No. | Main Area |
| :- | :--- | :--- | :--- |
| 1 | Harshit Pant | `cs26mt006` | Backend, database schema & migrations, seed script & dataset subset, roles & moderation, AI retrieval pipeline |
| 2 | Snehadip Ghoshal | `cs26mt010` | Frontend UI/UX, accessibility, Figma prototype, connecting frontend to API, Playwright E2E tests |
| 3 | Gangadevi Venkata Siva krishna | `cs26mt009` | OpenAPI 3.0.3 spec, authentication & security (Argon2id, CSRF), Docker/CI, pytest suite, AI guardrails & evaluation |
| 4 | Ritik Kumar | `cs26mt021` | PPT presentation, integration testing, and evaluation benchmarking |

## Milestone 3 (MS-3) Deliverables Included

1. **OpenAPI 3.0.3 YAML Specification (`docs/openapi.yaml` & `openapi.yaml`)**:
   - Complete contract defining **21 REST API paths** and **30 component schemas** across 9 functional tags (`System`, `Auth`, `Users`, `Categories`, `Resources`, `Ratings & Comments`, `Collections`, `AI Study Assistant`, `Moderation`), plus `SessionCookie` (`sp_session`) and `CsrfToken` (`X-CSRF-Token`) security schemes.
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

## Running Tests & RAG Evaluation Offline

```bash
# Run the integration test suite
python3 backend/tests/test_ms3_stack.py

# Run the 42-question RAG & Guardrail evaluation benchmark
python3 scripts/evaluate_rag.py
```
