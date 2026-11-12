# ScholarPulse - Database & Storage Guide

Database: MySQL 8.0 (Docker service `db`, volume `mysql_data`), utf8mb4. Schema is created by Alembic
(`0001_initial_schema` = 12 tables, `0002_profile_settings` = 4 extra columns on `users`).
Tables are accessed with raw parameterised SQL through `app/db/session.py` (no ORM in requests).

## How data is stored (overview)
| Data | Where | Notes |
| :-- | :-- | :-- |
| Accounts | `users` | Passwords stored only as salted Argon2id hash (`$argon2id$...`), never plain text. |
| Login session | Browser cookie `sp_session` | Stateless: signed token `{uid, role, sub, exp}` + HMAC-SHA256, HttpOnly, SameSite=Lax, 24 h. **No sessions/login-log table.** |
| CSRF | Token derived from the session cookie, sent in `X-CSRF-Token` header | Required on POST/PUT/PATCH/DELETE. |
| Resources (papers/notes) | `resources` | Full extracted text in `content_text` (HTML-escaped), short `tldr_summary`. |
| Searchable/AI chunks | `resource_chunks` | Text split into ~800 char chunks, 100 overlap; 64-d embedding stored as JSON text in `embedding_json`. FULLTEXT index for keyword fallback. |
| Uploaded .pdf/.txt files | **Not kept as files.** Text is extracted, stored in `resources.content_text`; only `file_name` and `file_size_bytes` are recorded. | Max 5 MB; scanned/empty PDFs rejected. |
| Profile photos | Disk: `/app/uploads/profile_photos/` (Docker volume `uploads_data`), path in `users.profile_photo_path` | |
| AI questions | `ai_queries` | Audit log: question, answer, cited chunk ids, fallback flag, latency. Rate limit 20/hour/user. |
| Alembic state | `alembic_version` (1 row) | Migration metadata, not an app table. |

## The 12 tables
### 1. users
`id` PK auto | `username` varchar(50) UNIQUE | `email` varchar(120) UNIQUE | `password_hash` varchar(255) | `bio` varchar(500) null |
`role` varchar(20) default `student` (student / ta / moderator) | `consent_accepted` bool default 1 | `created_at` datetime |
(0002) `programme` varchar(120) null | `profile_photo_path` varchar(500) null | `email_notifications` bool default 1 | `public_profile` bool default 1.
Index: `ix_users_role`.

### 2. categories (courses)
`id` PK | `course_code` varchar(20) UNIQUE (CS301, CS402, CS205, SE101) | `course_name` varchar(150) | `department` varchar(100) | `description` varchar(500) null | `created_at`.

### 3. resources
`id` PK | `title` varchar(200) | `content_text` text | `tldr_summary` varchar(1000) | `resource_type` varchar(30) default `paper_summary` |
`category_id` FK -> categories (RESTRICT) | `uploader_id` FK -> users (SET NULL) | `source_authors` varchar(500) | `source_ref` varchar(100) UNIQUE (arXiv id or `upload-<ms>-<uid>`) |
`published_on` date | `file_name` varchar(255) | `file_size_bytes` int | `is_official` bool (TA-published) | `rights_confirmed` bool | `status` varchar(20) default `active` |
`embedding_status` varchar(20) | `avg_rating` float | `rating_count` int | `comment_count` int | `created_at` | `updated_at`.
Indexes: `ix_resources_title`, `ix_resources_cat_status_rating` (category_id, status, avg_rating), `ix_resources_type_status_created`; FULLTEXT `ft_resources_title_content` (title, content_text).

### 4. resource_chunks
`id` PK | `resource_id` FK -> resources (CASCADE) | `chunk_index` int | `chunk_text` text | `char_length` int | `embedding_json` text (JSON array of 64 floats) |
`embedding_model` varchar(60) | `created_at`. UNIQUE (resource_id, chunk_index); index `ix_chunks_resource_idx`; FULLTEXT `ft_resource_chunks_text`.

### 5. tags
`id` PK | `name` varchar(60) UNIQUE | `slug` varchar(60) UNIQUE | `created_at`.

### 6. resource_tags (many-to-many)
`resource_id` FK (CASCADE) + `tag_id` FK (CASCADE) = composite PK | `created_at`. Index `ix_resource_tags_tag_id`.

### 7. ratings
`id` PK | `resource_id` FK (CASCADE) | `user_id` FK (CASCADE) | `score` int CHECK 1..5 | `created_at` | `updated_at`. UNIQUE (resource_id, user_id) = one rating per user per resource.

### 8. comments
`id` PK | `resource_id` FK (CASCADE) | `user_id` FK (CASCADE) | `body` text | `status` varchar(20) default `active` | `created_at` | `updated_at`. Index (resource_id, status, created_at).

### 9. collections (reading lists)
`id` PK | `title` varchar(150) | `description` varchar(1000) | `owner_id` FK -> users (CASCADE) | `category_id` FK -> categories (SET NULL) | `is_official` bool (TA list) | `is_public` bool | `created_at` | `updated_at`.

### 10. collection_items
`id` PK | `collection_id` FK (CASCADE) | `resource_id` FK (CASCADE) | `position` int | `notes` varchar(300) | `added_at`. UNIQUE (collection_id, resource_id); index (collection_id, position). Max 20 resources per collection for AI use.

### 11. reports (moderation)
`id` PK | `reporter_id` FK -> users (CASCADE) | `target_type` varchar(20) (resource/comment) | `target_id` int | `reason` varchar(50) | `details` varchar(1000) |
`status` varchar(20) default `open` | `moderator_id` FK -> users (SET NULL) | `moderation_action` varchar(30) | `moderation_note` varchar(500) | `created_at` | `resolved_at`.

### 12. ai_queries
`id` PK | `user_id` FK (SET NULL) | `scope_type` varchar(20) (resource/collection/course) | `scope_id` varchar(50) | `question` varchar(300) | `answer_text` text |
`cited_chunk_ids_json` varchar(500) | `not_found` bool | `fallback_used` bool | `model_used` varchar(60) | `latency_ms` int | `created_at`.

## Relationships
users 1-N resources (uploader), ratings, comments, collections, reports, ai_queries.
categories 1-N resources, collections. resources 1-N resource_chunks, ratings, comments; N-N tags via resource_tags; N-N collections via collection_items.

## Useful commands
```bash
docker exec -it scholarpulse-db mysql -u sp_user -psp_password_2026 scholarpulse
SHOW TABLES;  DESCRIBE users;  SELECT id,username,email,role,created_at FROM users;
SELECT COUNT(*) FROM resources;  SELECT * FROM alembic_version;
```
