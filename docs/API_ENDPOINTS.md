# ScholarPulse API — Endpoint Reference

Base URL: `http://localhost:8000/api/v1` · Interactive docs: `/docs` · Raw contract: `/api/v1/openapi.yaml`

The frontend (`frontend/index.html`) is served by the backend at `/`, so every call is **same-origin**. There is no mock data in the UI: each screen reads and writes through the endpoints below.

## Conventions

| Topic | Rule |
| :--- | :--- |
| Format | JSON in / JSON out. `POST /resources` is `multipart/form-data`. |
| Session | `sp_session` cookie (HttpOnly, SameSite=Lax), set by login/register, cleared by logout. |
| CSRF | Every `POST` / `PUT` / `PATCH` / `DELETE` on a protected endpoint needs header `X-CSRF-Token: <token>`. The token comes from `/auth/login`, `/auth/register` or `GET /auth/me` (use `/auth/me` to recover it after a page reload). |
| Errors | `{"detail": {"error": "CODE", "message": "Human text"}}`. Request-validation failures (422) use FastAPI's `detail: [{loc, msg, type}]` list. |
| Roles | `student` < `ta` < `moderator`. Anonymous visitors can read; everything that writes needs a session. |
| Pagination | `page` (≥1) and `page_size` (1–50) → `{items, total, page, page_size, total_pages}`. |

Common error codes: `UNAUTHORIZED` (401), `CSRF_INVALID` (403), `FORBIDDEN` (403), `TA_ROLE_REQUIRED` (403), `NOT_FOUND` (404), `DUPLICATE_ITEM` (409), `RATE_LIMIT_EXCEEDED` (429).

## Endpoint summary (31 operations: 21 documented paths + `/openapi.yaml`)

Legend — Auth: 🌐 public · 🔑 signed-in (+CSRF on writes) · 🛡️ moderator

| # | Method & path | Auth | Purpose |
| :-- | :--- | :-: | :--- |
| **System** | | | |
| 1 | `GET /health` | 🌐 | DB connectivity, Alembic revision, row counts for all 12 tables |
| 2 | `GET /openapi.yaml` | 🌐 | Raw OpenAPI 3.0.3 contract |
| **Auth & account** | | | |
| 3 | `POST /auth/register` | 🌐 | Create a student account (requires DPDP consent); signs in |
| 4 | `POST /auth/login` | 🌐 | Sign in with email (or username) + password |
| 5 | `POST /auth/logout` | 🔑 | Clear the session cookie |
| 6 | `GET /auth/me` | 🔑* | Current user + own uploads + fresh CSRF token (*401 if signed out) |
| 7 | `PATCH /auth/me` | 🔑 | Update `username` / `bio` |
| 8 | `PUT /auth/password` | 🔑 | Change password |
| 9 | `DELETE /auth/me` | 🔑 | Delete account and all owned data (DPDP Act 2023) |
| **Reference data** | | | |
| 10 | `GET /categories` | 🌐 | Courses with active resource counts |
| 11 | `GET /tags` | 🌐 | Top 40 tags with usage counts |
| **Resources** | | | |
| 12 | `GET /resources` | 🌐 | Search / filter / sort / paginate the library |
| 13 | `POST /resources` | 🔑 | Upload a `.pdf`/`.txt` (≤ 5 MB); text is extracted, chunked, embedded |
| 14 | `GET /resources/{resource_id}` | 🌐 | Full detail incl. text, tags, `chunk_count` |
| 15 | `PATCH /resources/{resource_id}` | 🔑 owner / 🛡️ | Edit the title |
| 16 | `DELETE /resources/{resource_id}` | 🔑 owner / 🛡️ | Delete a resource |
| **Ratings & comments** | | | |
| 17 | `POST /resources/{resource_id}/ratings` | 🔑 | Create or update your 1–5 rating (one per user) |
| 18 | `GET /resources/{resource_id}/comments` | 🌐 | Active comments, newest first |
| 19 | `POST /resources/{resource_id}/comments` | 🔑 | Post a comment |
| 20 | `DELETE /comments/{comment_id}` | 🔑 author / 🛡️ | Delete a comment |
| **Collections (reading lists)** | | | |
| 21 | `GET /collections` | 🌐 / 🔑 | List public lists (official first); `mine=true` lists your own incl. private |
| 22 | `POST /collections` | 🔑 | Create a list (`is_official` needs TA/moderator) |
| 23 | `GET /collections/{collection_id}` | 🌐 | Detail with ordered items (private lists: owner/moderator only) |
| 24 | `PATCH /collections/{collection_id}` | 🔑 owner / 🛡️ | Edit title/description, reorder items |
| 25 | `DELETE /collections/{collection_id}` | 🔑 owner / 🛡️ | Delete a list |
| 26 | `POST /collections/{collection_id}/items` | 🔑 owner / 🛡️ | Add a resource (max 20 per list) |
| 27 | `DELETE /collections/{collection_id}/items/{resource_id}` | 🔑 owner / 🛡️ | Remove a resource |
| **AI study assistant** | | | |
| 28 | `POST /ai/ask` | 🔑 | Grounded Q&A over a resource, collection or course |
| **Reports & moderation** | | | |
| 29 | `POST /reports` | 🔑 | Report a resource or comment |
| 30 | `GET /moderation/reports` | 🛡️ | Moderation queue (optional `status` filter) |
| 31 | `PATCH /moderation/reports/{report_id}` | 🛡️ | Hide / restore / remove / dismiss, with audit note |

(The OpenAPI file groups methods by path, so these 31 rows appear under 21 path entries.)

---

## System

### `GET /health`
```json
{ "status": "ok", "service": "ScholarPulse Backend", "database": "connected",
  "alembic_revision": "0001_initial_schema",
  "counts": { "users": 20, "resources": 630, "resource_chunks": 1313, "...": 0 } }
```

## Auth & account

### `POST /auth/register` → 201
Body: `{ "username": "str 3-50", "email": "str", "password": "str 8-128", "bio": "str ≤500 | null", "consent_accepted": true }`
Returns the user plus `csrf_token`; sets the session cookie.
Errors: `400 CONSENT_REQUIRED`, `400 DUPLICATE_USER`.

### `POST /auth/login`
Body: `{ "email": "sam.green@university.edu", "password": "…" }` (the `email` field also accepts a username).
Returns `{ "user": {id, username, email, bio, role, consent_accepted, created_at}, "csrf_token": "…" }`.
Errors: `401 INVALID_CREDENTIALS`.

### `GET /auth/me`
Returns the user fields above **plus** `csrf_token`, `uploads` (resource summaries) and `collections_count`. `401 UNAUTHORIZED` when not signed in — the frontend uses this on page load to restore the session.

### `PATCH /auth/me`
Body: `{ "username": "…", "bio": "…" }` (both optional). Errors: `400 DUPLICATE_USER` when the username is taken.

### `PUT /auth/password`
Body: `{ "current_password": "…", "new_password": "min 8" }` → `{ "status": "password_updated" }`. Error: `400 INVALID_PASSWORD`.

### `DELETE /auth/me`
→ `{ "status": "account_deleted", "deleted_user_id": 7 }`. Removes ratings, comments, collections, uploads and AI history, and clears the cookie.

## Reference data

### `GET /categories`
`[{ "id", "course_code": "CS301", "course_name", "department", "description", "resource_count" }]`

### `GET /tags`
`[{ "id", "name", "slug", "usage_count" }]`

## Resources

### `GET /resources`
| Query param | Type | Notes |
| :--- | :--- | :--- |
| `q` | string | Substring match on title, text and authors |
| `course_code` | string | e.g. `CS301` |
| `resource_type` | string | `lecture_notes` · `slides` · `assignment` · `paper_summary` |
| `tag` | string | Tag name or slug |
| `official_only` | bool | Verified resources only |
| `sort_by` | string | `rating` (default) · `newest` · `comments` |
| `page`, `page_size` | int | Default `1` / `20`, max page size `50` |

Returns `{ items: [ResourceSummary], total, page, page_size, total_pages }` where a summary has
`id, title, resource_type, course_code, source_authors, source_ref, published_on, tldr_summary, is_official, status, embedding_status, avg_rating, rating_count, comment_count, tags[], uploader_username, created_at`.

### `POST /resources` → 201 (`multipart/form-data`)
| Field | Required | Notes |
| :--- | :-: | :--- |
| `file` | ✓ | `.pdf` or `.txt`, ≤ 5 MB, must contain extractable text |
| `title` | ✓ | ≤ 200 chars |
| `course_code` | ✓ | One of `/categories` |
| `resource_type` | | default `lecture_notes` |
| `tags` | | comma-separated |
| `is_official` | | TA / moderator only |
| `rights_confirmed` | ✓ | must be `true` |

Returns a `ResourceSummary` + `content_text`, `chunk_count`, `file_name`, `file_size_bytes`.
Errors: `400 RIGHTS_NOT_CONFIRMED | INVALID_FILE_TYPE | FILE_TOO_LARGE | EMPTY_OR_SCANNED_FILE | INVALID_COURSE`, `403 TA_ROLE_REQUIRED`.

### `GET /resources/{resource_id}`
`ResourceSummary` + `content_text`, `chunk_count`, `file_name`, `file_size_bytes`. `404` for missing, hidden or removed resources.

### `PATCH /resources/{resource_id}` · `DELETE /resources/{resource_id}`
Owner or moderator only (`403 FORBIDDEN` otherwise). PATCH body `{ "title": "…" }` returns the updated detail; DELETE returns `{ "status": "deleted", "resource_id": 12 }`.

## Ratings & comments

### `POST /resources/{resource_id}/ratings`
Body `{ "score": 1-5 }` → `{ resource_id, user_id, score, avg_rating, rating_count }`. Re-rating updates your previous score.

### `GET /resources/{resource_id}/comments`
`[{ id, resource_id, user_id, username, body, status, created_at }]`

### `POST /resources/{resource_id}/comments` → 201
Body `{ "body": "2-2000 chars" }` → the created comment.

### `DELETE /comments/{comment_id}`
Author or moderator → `{ "status": "deleted", "comment_id": 5 }`.

## Collections

### `GET /collections`
Query: `course_code`, `official_only` (bool), `mine` (bool — requires a session; includes private lists).
Returns `[{ id, title, description, owner_id, owner_username, course_code, is_official, is_public, created_at, item_count }]`, official lists first.

### `POST /collections` → 201
Body `{ "title": "3-150", "description": "…", "course_code": "CS301", "is_public": true, "is_official": false }`. `is_official=true` needs TA/moderator (`403 TA_ROLE_REQUIRED`).

### `GET /collections/{collection_id}`
Summary + `items: [{ position, notes, resource: ResourceSummary }]`. A private list returns `404` to anyone but its owner or a moderator.

### `PATCH /collections/{collection_id}`
Body (all optional): `{ "title", "description", "ordered_resource_ids": [3, 1, 2] }` — the id order becomes the new item order. Returns the detail.

### `DELETE /collections/{collection_id}`
→ `{ "status": "deleted", "collection_id": 4 }`

### `POST /collections/{collection_id}/items` → 201
Body `{ "resource_id": 12, "position": null, "notes": "optional" }` → collection detail.
Errors: `404` unknown collection/resource, `409 DUPLICATE_ITEM`, `400 COLLECTION_FULL` (20-resource cap).

### `DELETE /collections/{collection_id}/items/{resource_id}`
→ `{ "status": "removed", "collection_id": 4, "resource_id": 12 }`

## AI study assistant

### `POST /ai/ask`
```json
{ "question": "Why does BFS find shortest paths?",
  "scope_type": "resource",            // resource | collection | course
  "scope_id": "1",                     // resource id | collection id | course code (e.g. "CS301")
  "simulate_failure": false }          // true → force the keyword-fallback path
```
Response:
```json
{ "query_id": 41, "question": "…", "scope_type": "resource", "scope_id": "1",
  "answer": "… [Chunk 12] …",
  "not_found": false,                  // true → "Not found in this document"
  "fallback_used": false,              // true → keyword matches, not an AI answer
  "fallback_notice": null,
  "citations": [{ "chunk_id": 12, "resource_id": 1, "resource_title": "…", "chunk_index": 0,
                  "similarity_score": 0.81, "snippet": "…" }],
  "model_used": "gemini-2.5-flash",    // or "local-extractive" (no API key) / "mysql-fulltext-fallback"
  "latency_ms": 37 }
```
Answer generation: with `GEMINI_API_KEY` set, the server retrieves the best chunks, sends them to Gemini (`GEMINI_GENERATION_MODEL`, server-side only) inside `<untrusted_document_chunk>` tags, and keeps only citations that were really retrieved. If Gemini times out (10 s + 1 retry), hits quota, or errors, the response switches to `fallback_used: true` with keyword-matched passages. With no key the built-in offline extractive answer is used.

Guardrails: question ≤ 300 chars (`400 QUESTION_TOO_LONG`), 20 questions / user / hour (`429 RATE_LIMIT_EXCEEDED`), invalid scope (`400 INVALID_SCOPE`), prompt-injection stripping, citation validation, refusal when nothing relevant is retrieved. Every query is logged in `ai_queries`.

## Reports & moderation

### `POST /reports` → 201
Body `{ "target_type": "resource | comment", "target_id": 12, "reason": "…", "details": "≤1000 chars | null" }`
`reason` ∈ `incorrect_or_misleading`, `copyright_concern`, `low_quality_or_spam`, `inappropriate_content` (`400 INVALID_REASON` otherwise). `404` if the target does not exist.

### `GET /moderation/reports?status=open|resolved|dismissed` (moderator)
Open reports first. Each row: report fields + `reporter_username`, `target_title_or_preview`, `moderation_action`, `moderation_note`, `resolved_at`.

### `PATCH /moderation/reports/{report_id}` (moderator)
Body `{ "action": "hide | restore | remove | dismiss", "note": "optional audit note" }`.
`hide`/`remove` set the target's status to `hidden`/`removed` (excluded from browse and AI scope), `restore` sets it back to `active`, `dismiss` leaves content untouched. The report becomes `resolved` (or `dismissed`) with the moderator id, action, note and timestamp recorded.

---

## Which screen calls which endpoint

| Screen | Endpoints |
| :--- | :--- |
| Boot / header | `GET /health`, `GET /auth/me`, `GET /categories`, `GET /tags` |
| Home | `GET /collections`, `GET /resources?sort_by=newest` |
| Explore | `GET /resources` (search, course, type, tag, verified, sort, page), `POST /ai/ask` (course scope) |
| Resource detail | `GET /resources/{id}`, `GET …/comments`, `POST …/comments`, `DELETE /comments/{id}`, `POST …/ratings`, `DELETE /resources/{id}`, `POST /ai/ask` (resource scope), `GET /collections?mine=true` + `POST /collections/{id}/items` |
| Report form | `POST /reports` |
| Collections / detail | `GET /collections`, `POST /collections`, `GET /collections/{id}`, `DELETE /collections/{id}`, `DELETE …/items/{resource_id}`, `POST /ai/ask` (collection scope) |
| Upload / status | `POST /resources` |
| Sign in / Create account | `POST /auth/login`, `POST /auth/register` |
| Profile | `GET /auth/me`, `PATCH /auth/me`, `PUT /auth/password`, `DELETE /auth/me`, `POST /auth/logout`, `GET /collections?mine=true` |
| Moderation queue / confirm | `GET /moderation/reports`, `PATCH /moderation/reports/{id}` |

Not used by the UI: `PATCH /resources/{id}`, `PATCH /collections/{id}` (reordering), `GET /openapi.yaml`.

## Quick try (curl)

```bash
# Sign in and keep the cookie + CSRF token
curl -s -c jar.txt -H 'Content-Type: application/json' \
  -d '{"email":"sam.green@university.edu","password":"ScholarPulse!2026"}' \
  http://localhost:8000/api/v1/auth/login
# → {"user": {...}, "csrf_token": "<TOKEN>"}

# Ask the AI about resource 1
curl -s -b jar.txt -H 'Content-Type: application/json' -H 'X-CSRF-Token: <TOKEN>' \
  -d '{"question":"Why does BFS find shortest paths?","scope_type":"resource","scope_id":"1"}' \
  http://localhost:8000/api/v1/ai/ask
```

Seeded demo accounts (password `ScholarPulse!2026`): `sam.green@university.edu` (student), `snehadip.ghoshal@university.edu` (TA), `harshit.pant@university.edu` (moderator).
