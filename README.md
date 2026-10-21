Here is the complete content for your `README.md` file. Copy and paste this directly into your `README.md` file in VS Code, replace the teammate name placeholders with your actual team members' names and roll numbers, and save it:

```markdown
# ScholarPulse — AI-Enabled Academic Knowledge Hub
**Course Project 2026 | Theme 4: Knowledge Hub**

---

## Milestone 1 (MS-1): Problem Statement & Design Document

### 1. Overview
* **Website Name:** ScholarPulse
* **Team Members:**
  1. **Snehadip Kumar Ghoshal** (Roll No: cs26mt010) — Backend Architecture, Database & AI Engineering
  2. **[Teammate 2 Name]** (Roll No: [Roll No]) — Frontend UI/UX, Accessibility & Playwright E2E Testing
  3. **[Teammate 3 Name]** (Roll No: [Roll No]) — OpenAPI Spec, Security, Docker/CI & Pytest Suite
  4. **[Teammate 4 Name]** (Roll No: [Roll No])
* **One-Paragraph Description:** ScholarPulse is a collaborative multi-page academic knowledge hub where university students and researchers upload, search, rate, comment on, and organize course notes, research paper summaries, and reading lists. To solve information overload during exam preparation and literature reviews, the platform integrates a server-side AI Study Assistant (powered by Google Gemini 2.5 Flash) that automatically generates concise TL;DR summaries, suggests taxonomy tags, and answers user questions strictly grounded in the uploaded document text—with automatic graceful degradation to a local extractive keyword engine if the external LLM service is slow or unavailable.
* **Target Users:** Undergraduate and postgraduate students seeking peer-reviewed course notes, teaching assistants curating course reading lists, and academic researchers conducting literature reviews.

---

### 2. Dataset Specification
* **Primary Dataset Source & License:** 
  * **Cornell University arXiv Metadata Dataset (Kaggle):** `https://www.kaggle.com/datasets/Cornell-University/arxiv`
  * **License:** CC0 1.0 Universal (Public Domain Dedication) — free for academic and commercial redistribution.
* **Synthetic Data Augmentation (`backend/app/seed.py`):**
  * To simulate a live campus portal with active users, our deterministic seed script populates initial academic categories (`CS301`, `CS402`, `CS205`, `SE101`), user accounts with Argon2id salted password hashes, tags, peer reviews (1–5 star ratings + comments), and curated reading collections automatically during `docker compose up`.
* **Field Mapping to Database Schema:**
  * `title` -> `resources.title` (indexed `VARCHAR(200)`)
  * `abstract` / study notes -> `resources.content_text` (`TEXT`)
  * `categories` -> mapped to normalized `categories` (`code`, `name`) and many-to-many `tags` via `resource_tags`
  * `authors` / contributors -> mapped to `users` (`id`, `username`, `email`, `bio`)

---

### 3. Content Structure (Sitemap — 7 Distinct Pages)
```text
[1. Home / Discovery Feed (/)]
 ├──> [2. Explore & Filter Catalog (/explore)]
 │     └──> [3. Resource Detail, Peer Reviews & Grounded AI Q&A (/resources/:id)]
 ├──> [4. Curated Reading Lists / Collections Hub (/collections)]
 ├──> [5. Publish / Upload Study Notes (/upload)] (Authenticated Users)
 ├──> [6. Authentication Portal + DPDP Act 2023 Consent Notice (/auth)]
 └──> [7. User Profile, Bio Editor & Right-to-Erasure Account Deletion (/profile)] (Authenticated Users)

```

---

### 4. Functionality & Page-by-Page Breakdown

| Page / Screen | What the Screen Shows | What a User Can Do |
| --- | --- | --- |
| **1. Home (`/`)** | Hero banner, platform overview, and top 3 featured/recent study notes with cached AI TL;DR previews and tags. | Navigate to catalog, jump to upload page, or click any featured resource to read and query it. |
| **2. Explore Catalog (`/explore`)** | Search bar, course category dropdown filter, and paginated list of resources with summary snippets and tags. | Search by keyword, filter by university course code, and select a document to view full details. |
| **3. Resource Detail (`/resources/:id`)** | Full note text, author info, cached AI TL;DR summary, interactive **AI Q&A panel**, star ratings, and peer review thread. | Ask natural-language questions to the AI assistant, post a 1–5 star review, or delete the resource (if owner). |
| **4. Collections Hub (`/collections`)** | Grid of curated reading lists (e.g., "Midterm Exam Prep") with titles and descriptions. | Browse study collections or create a new themed reading collection (authenticated users). |
| **5. Publish Notes (`/upload`)** | Accessible form with Title, Course Category selector, comma-separated Tags, and full Markdown/Text notes input. | Submit new study notes; backend validates input, caches an initial AI summary, and persists to MySQL. |
| **6. Auth Portal (`/auth`)** | Sign-In form and Registration form with explicit **DPDP Act 2023 Data Consent checkbox**. | Log in (sets HttpOnly JWT cookie) or register a new account after consenting to data usage policy. |
| **7. Profile & Privacy (`/profile`)** | Logged-in user's username, email, academic bio, DPDP consent status, and account management controls. | Update academic bio, log out, or click **"Delete Account & All Data"** (cascading erasure per DPDP Act 2023). |

#### 10 User Stories

1. **As a visitor**, I want to browse and search study notes without logging in so that I can evaluate the platform's usefulness before creating an account.
2. **As a student**, I want to filter course notes by specific course codes (e.g., `CS301`) so that I only see materials relevant to my current classes.
3. **As a visitor**, I want to read peer reviews and 1–5 star ratings on uploaded notes so that I can trust the accuracy of the study material.
4. **As a prospective user**, I want to see a clear DPDP Act 2023 consent notice during registration so that I know what personal data is collected and why.
5. **As a registered student**, I want to publish my course notes with custom tags and course categories so that I can contribute to my peers' exam preparation.
6. **As a content owner**, I want the system to restrict edit and delete permissions strictly to my own uploaded resources so that no other user can tamper with my work.
7. **As a student**, I want to view an automatic TL;DR summary on every resource page so that I can quickly decide if a long document is worth reading in full.
8. **As a student**, I want to ask specific questions to an AI assistant grounded strictly in the uploaded note's text so that I get accurate explanations without external hallucinations.
9. **As a user**, I want the site to fall back to a local extractive summary if the external AI API is slow or out of quota so that my study session is never interrupted.
10. **As a privacy-conscious user**, I want to permanently delete my account and all associated posts and reviews with one click so that I can exercise my right to erasure.

---

### 5. AI Feature Proposal (Phase C)

* **Feature:** Grounded Document Q&A Assistant (RAG) + Automated Executive Summarizer.
* **Model / API:** Google **Gemini API (`gemini-2.5-flash`)** called exclusively from the Python FastAPI backend (`backend/app/ai_service.py`) using the `GEMINI_API_KEY` environment variable.
* **Data Transmitted & Privacy Guarantees:** Only the public resource title, resource body text (truncated to 4,000 characters), and sanitized user question (capped at 300 characters) are sent to the API. **Zero PII** (no passwords, emails, usernames, or user IDs) is ever transmitted.
* **Guardrails & Security:**
* Per-user rate limiting (15 requests/hour) enforced server-side.
* Regex prompt-injection filter blocks override phrases (e.g., *"ignore previous instructions"*, *"reveal your api key"*).
* Untrusted document content and user questions are isolated inside `<document_context>` and `<user_question>` XML tags.


* **Failure Mode & Graceful Degradation:**
* All Gemini API requests enforce a strict **4.5-second timeout**.
* If the external API times out, returns a `429`/`5xx` error, or has no key configured, the backend catches the exception and seamlessly returns a `200 OK` response computed by our deterministic **Local Extractive Fallback Engine** (`degraded: true`), accompanied by a clear UI notice.



---

## Quick Start (Single-Command Docker Compose)

```bash
git clone [https://github.com/cs26mt010-tech/scholarpulse](https://github.com/cs26mt010-tech/scholarpulse)
cd scholarpulse
docker compose up --build

```

* **Frontend Web App:** `http://localhost:3000`
* **Backend REST API & Swagger UI:** `http://localhost:8000/docs`

```

```