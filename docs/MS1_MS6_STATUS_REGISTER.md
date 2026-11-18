# MS-1 to MS-6 Status and Sign-off Register

This register tracks what is in the repository versus what still requires live or external evidence.

| Milestone | Repository artifacts | Remaining verification / external evidence |
|---|---|---|
| MS-1 | Problem/design, dataset subset, seed notes, README and project structure | Verify GitHub collaborators and branch protection |
| MS-2 | ER diagram, schema/index guide, accessibility checklist | Attach Figma export/share link and walkthrough; complete live keyboard/focus/contrast checks |
| MS-3 | OpenAPI, FastAPI routes, Alembic revisions, seed script, Docker Compose | Run fresh-clone Docker test and retain logs |
| MS-4 | Pytest suite, CI workflow, 60% coverage gate, Playwright smoke tests | Push and confirm remote CI; attach reviewed/approved PR links |
| MS-5 | Auth, roles, upload, collections, ratings/comments, reports/moderation and AI scope endpoints are represented in source | Full feature regression; production Gemini embedding/generation is not verified as active; real credentials and live evaluation required |
| MS-6 | Final report, presentation deck and demo runbook | Live demo, recording, team sign-off and submission of external evidence |

## Release decision

Do not mark all milestones fully accepted until each external verification item is attached and the relevant tests pass. The deterministic local RAG baseline is not equivalent to a verified live Gemini integration.

## Verification log (5 Nov 2026)

Re-verified locally after fixes:

- `ruff check backend scripts` passes (`ruff.toml` pins rules; unused imports and semicolon statements fixed).
- Plain `pytest backend/tests/test_ms3_stack.py --cov=app --cov-fail-under=60` passes (`pytest.ini` adds the import path); 8 tests, about 74% coverage. `conftest.py` now resets the SQLite test DB each run.
- `scripts/evaluate_rag.py` runs 42 questions against the deterministic local baseline (not live Gemini).
- Playwright: 7 tests pass locally against a seeded API (3 new UI flows in `frontend/e2e/flows.spec.js`: sign-in, wrong password, Ask AI).

Still needs external evidence: GitHub collaborators/branch protection, Figma link, fresh-clone Docker logs, green remote CI run, reviewed PR links, live Gemini evaluation, demo recording.
