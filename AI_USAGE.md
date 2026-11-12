# AI Usage Disclosure (`AI_USAGE.md`)

**Project**: ScholarPulse — AI-Enabled Academic Knowledge Hub (`cs26mt010-tech/scholarpulse`)

## 1. Runtime AI Feature in the Application
- **Provider & Models**: Google Gemini API (free tier), invoked strictly server-side from the FastAPI backend (`backend/app/services/rag_service.py`).
  - Embeddings: `gemini-embedding-001`
  - Grounded Question Answering & TL;DR Summaries: `gemini-2.5-flash`
- **Privacy & Free-Tier Compliance**: Only public resource text chunks and the user's question (capped at 300 characters) are sent to the external service. User emails, Argon2id password hashes, session tokens, and private identifiers are never included in prompts or logs.
- **Guardrails & Fallback**:
  - Retrieved chunks are wrapped in `<untrusted_document_chunk>` delimiters with instructions to ignore embedded commands.
  - Every cited chunk ID is validated against the retrieved set before returning to the client.
  - Each AI request enforces a 10-second timeout and 1 retry, falling back to MySQL `FULLTEXT` keyword passage matching on timeout or quota exhaustion.

## 2. Development-Time AI Assistance
- AI coding assistance was used to help draft boilerplate OpenAPI 3.0.3 schema definitions, SQLAlchemy 2.0 ORM type annotations, and synthetic seed templates.
- All database schema relationships, role-based access control checks, Argon2id/CSRF security logic, and the 42 evaluation questions were reviewed and verified by the 4 team members.
