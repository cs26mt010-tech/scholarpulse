# ScholarPulse — MS-2 / MS-3 implementation map

This document connects the ScholarPulse prototype work, the MS-1 requirements, the MS-2 ER diagram and the MS-3 backend deliverables. The prototype export must be attached separately to the submission package; it is not included in this source ZIP. The product is ScholarPulse (not the CampusSwap example used in the MS-2 teaching handout).

## 1. Prototype screens and backend coverage

| Prototype screen / state | Backend operation(s) | Notes |
|---|---|---|
| Home | `GET /api/v1/resources`, `GET /api/v1/collections`, `GET /api/v1/categories`, `GET /api/v1/tags` | Home cards, featured collections, recent resources and course shortcuts use real catalogue data. |
| Explore / Resource library | `GET /api/v1/resources`, `GET /api/v1/categories`, `GET /api/v1/tags` | Supports keyword, course, tag, resource type, verified/official filter, sorting and pagination. |
| Resource detail | `GET /api/v1/resources/{resource_id}`, `GET /api/v1/resources/{resource_id}/comments` | Includes text, course, uploader, tags, rating summary and chunk count. |
| Ask this document / AI answer | `POST /api/v1/ai/ask` | Contract supports resource, collection and course scopes; response includes citations, not-found and fallback fields. The Gemini production pipeline is a later AI milestone; this MS-3 build includes a deterministic local retrieval/extractive baseline and simulated failure path. |
| Rate resource | `POST /api/v1/resources/{resource_id}/ratings` | One rating per user/resource; subsequent rating updates the existing score. |
| Add comment | `POST /api/v1/resources/{resource_id}/comments` | Requires login and CSRF token. |
| Report content form | `POST /api/v1/reports` | Supports resource/comment targets and the report reasons used by the UI. |
| Collections hub | `GET /api/v1/collections`, `POST /api/v1/collections` | Public lists; official TA lists appear first; `mine=true` returns the current user's private and public lists. |
| Collection detail | `GET /api/v1/collections/{collection_id}`, `PATCH /api/v1/collections/{collection_id}`, `DELETE /api/v1/collections/{collection_id}` | Ordered resources, owner editing, and visibility checks. |
| Add/remove/reorder collection resources | `POST /api/v1/collections/{collection_id}/items`, `DELETE /api/v1/collections/{collection_id}/items/{resource_id}`, `PATCH /api/v1/collections/{collection_id}` | Duplicate prevention and 20-resource AI scope limit. |
| Upload study notes | `POST /api/v1/resources` | PDF/TXT, 5 MB maximum, rights confirmation, text extraction, chunking and tag association. Scanned PDFs with no extractable text are rejected. |
| Sign up | `POST /api/v1/auth/register` | Requires consent; Argon2id password hash; session cookie and CSRF token returned. |
| Sign in | `POST /api/v1/auth/login` | Email or username plus password; returns session cookie and CSRF token. |
| Sign out | `POST /api/v1/auth/logout` | Clears the session cookie. |
| Profile / My profile | `GET /api/v1/auth/me`, `PATCH /api/v1/auth/me`, `DELETE /api/v1/auth/me`, `GET/POST /api/v1/auth/me/photo` | Current user, uploads and collection count; edit display name/programme, notification and public-profile preferences, upload/retrieve profile photo; delete account and associated data. |
| Change password | `PUT /api/v1/auth/password` | Verifies current password before updating the hash. |
| Moderation queue | `GET /api/v1/moderation/reports` | Moderator-only queue with status filter and reported target details. |
| Moderation actions | `PATCH /api/v1/moderation/reports/{report_id}` | Hide, restore, remove or dismiss; stores moderator, action, note and resolution timestamp. |

## 2. Prototype-only states and scope decisions

- **Google sign-in:** the PDF labels this as a demo prototype. MS-1 specifies Argon2id account authentication and does not define Google OAuth credentials or callback handling. The backend therefore does not pretend to authenticate Google accounts. Add OAuth only if the team explicitly expands scope and configures a provider client ID/secret.
- **Password reset:** the prototype shows a reset-link confirmation state, but MS-1 does not specify a reset-token table, email provider, expiry or delivery workflow. This is not represented as a working email feature in MS-3. It needs a separate decision before being implemented.
- **Prototype AI unavailable state:** `POST /api/v1/ai/ask` returns `fallback_used` and `fallback_notice`; the request's `simulate_failure` flag is for demonstrating/testing the fallback state. The deterministic retrieval/extractive implementation is a development baseline, not a claim that Gemini is configured.
- **Upload limit:** MS-1 defines 5 MB for PDF/TXT uploads. The MS-2 teaching example's 2 MB photo limit belongs to the unrelated CampusSwap example and is not applied to ScholarPulse.

## 3. Data model (12 application tables)

The Alembic migration creates the 12 application tables: `users`, `categories`, `resources`, `resource_chunks`, `tags`, `resource_tags`, `ratings`, `comments`, `collections`, `collection_items`, `reports`, and `ai_queries`. Alembic's own `alembic_version` table is migration metadata, not an application entity.

- `users` 1—many `resources`, `ratings`, `comments`, `collections`, `reports`, and `ai_queries`.
- `categories` 1—many `resources` and `collections`.
- `resources` 1—many `resource_chunks`, `ratings`, `comments`, `reports` (polymorphic target), and `collection_items`.
- `resources` many—many `tags` through `resource_tags`.
- `collections` many—many `resources` through `collection_items`; the join table stores position and notes.
- `ratings` has a unique `(resource_id, user_id)` pair; `collection_items` has a unique `(collection_id, resource_id)` pair.
- `resource_chunks` has a unique `(resource_id, chunk_index)` pair.

The migration includes indexes for course/status/rating browse, type/status/date sorting, chunk retrieval, comments by resource/status/date, collection ordering, report queue ordering and AI query rate-limit lookup. MySQL 8 adds FULLTEXT indexes for chunk and resource text.

## 4. API conventions

- Base path: `/api/v1`; interactive docs: `/docs`; ReDoc: `/redoc`; contract: `docs/openapi.yaml` and `/api/v1/openapi.yaml`.
- JSON fields use `snake_case`.
- List endpoints paginate with `page` and `page_size` (maximum 50).
- Session: HttpOnly `sp_session` cookie, 24-hour expiry, SameSite=Lax; Secure should be enabled behind production HTTPS.
- State-changing authenticated requests require `X-CSRF-Token`. Retrieve a fresh token using `GET /api/v1/auth/me` after page reload.
- Roles: visitor (read-only), student, TA and moderator. Official collection/resource publishing is restricted to TA/moderator; moderation endpoints are moderator-only.
- Password hashes are never returned. All database writes use parameterised SQL; user content is escaped before rendering.

## 5. Run from a fresh clone

```bash
cp .env.example .env
docker compose up --build
```

The API container waits for MySQL health, runs `alembic upgrade head`, runs the deterministic idempotent seed script, then starts Uvicorn. Open `http://localhost:8000/docs` and `http://localhost:8000/api/v1/health`.

Local tests without Docker:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r backend/requirements.txt
pytest backend/tests -q
```

The pytest `conftest.py` selects an isolated SQLite test database when `DATABASE_URL` is not set, applies the Alembic migration and seeds the committed dataset. CI can provide its MySQL service URL instead.

## 6. Seed accounts (development only)

All deterministic demo accounts use the development password `ScholarPulse!2026`. The seed includes student, TA and moderator roles. Change/remove these credentials before any public deployment; never use the demo password in production.

Examples:
- Student: `sam.green@university.edu`
- TA: `snehadip.ghoshal@university.edu`
- Moderator: `harshit.pant@university.edu`

## 7. Milestone deliverables checklist

### MS-2
- [x] Clickable prototype PDF supplied, including Home, Explore, Resource detail, collections, upload, auth, profile and moderation flows/states.
- [x] ER diagram PDF supplied; 3NF entities, PK/FK, cardinalities and index note are represented in the MS-2 deliverable.
- [ ] Team still needs to ensure the Figma share link is viewable by the instructor and submit the required short screen recording (the PDF alone cannot prove these submission steps).
- [ ] Run a WCAG AA contrast check and verify every control has a visible label and keyboard focus. The PDF describes the design; it cannot prove live-site keyboard behaviour.

### MS-3
- [x] `docs/openapi.yaml` — OpenAPI 3.0.3 contract.
- [x] FastAPI backend covering the documented resources and roles.
- [x] 12-table Alembic migration, including uniqueness constraints and indexes.
- [x] Deterministic, idempotent seed script using committed dataset files (no download required).
- [x] Dockerfile, Docker Compose and healthcheck/entrypoint sequence.
- [x] Automated integration tests for API, roles, CSRF, uploads, AI retrieval/fallback and moderation.
- [ ] Docker Compose fresh-clone test must still be run on a machine with Docker installed; this environment did not have Docker available.

### ER diagram source

The normalized ScholarPulse diagram is provided as [`ER_DIAGRAM.mmd`](ER_DIAGRAM.mmd) (Mermaid ER syntax). Render it in Mermaid Live Editor or a Markdown viewer that supports Mermaid to export a diagram PDF. `reports.target_type/target_id` is intentionally polymorphic (resource or comment), so `target_id` is not a conventional FK; the API validates the target before inserting the report.

A ready-to-submit diagram export is also included at [`ScholarPulse_ER_Diagram.pdf`](ScholarPulse_ER_Diagram.pdf), generated from [`ER_DIAGRAM.dot`](ER_DIAGRAM.dot). Review it against your team's final naming decisions before submitting.
