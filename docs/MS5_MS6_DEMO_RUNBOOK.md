# ScholarPulse Final Demo Runbook (MS-5 / MS-6)

## Pre-demo safety
- Use a local development database and demo accounts only.
- Do not expose `.env`, session cookies, passwords or API keys on screen.
- Do not run `docker compose down -v` on a database containing work you need.
- Confirm whether the AI path is deterministic fallback or live Gemini before describing it.

## Start
```powershell
Copy-Item .env.example .env
docker compose up --build -d
docker compose ps
docker compose logs --tail 100 backend
```

## Demo sequence
1. Health: `http://localhost:8000/api/v1/health`
2. Swagger: `http://localhost:8000/docs`
3. Home and Explore: `http://localhost:8000/`
4. Search and paginate resources.
5. Open a resource detail.
6. Sign in as a student and demonstrate a permitted operation.
7. Upload a small text/PDF file and show validation behavior.
8. Create a collection and add a resource.
9. Sign in as TA and demonstrate official publishing if enabled in the UI.
10. Sign in as moderator and demonstrate report review/action.
11. Ask a question in resource/collection/course scope; explain citations and fallback status.
12. Show Pytest, coverage, Playwright and remote GitHub Actions evidence.

## Demo accounts
The implementation guide documents the development-only password `ScholarPulse!2026`.
Examples: `sam.green@university.edu` (student), `snehadip.ghoshal@university.edu` (TA),
`harshit.pant@university.edu` (moderator). Confirm these accounts exist in the local seed
before the demo. Change all demo credentials before any public deployment.

## MS-5 verification gates
- Exercise register/login/logout and session expiry.
- Verify role checks for student, TA and moderator.
- Verify PDF/TXT upload limits, empty/scanned PDF rejection and chunk persistence.
- Verify rating uniqueness/update, comments and collection ownership.
- Verify report queue, hide/restore/remove/dismiss actions and audit data.
- Exercise resource, collection and course AI scopes.
- Test unanswerable questions, injected instructions, citations, timeout and keyword fallback.
- If Gemini is enabled, test actual embedding and generation with a server-side key; record
  model IDs, latency, timeout behavior and evaluation metrics. Do not commit the key.

## MS-6 submission evidence
- Final report PDF and source Markdown.
- Presentation deck.
- Figma share URL/export and walkthrough recording.
- Accessibility test record with tester/date/results.
- GitHub Actions successful run URL.
- Reviewed/approved PR links.
- Final demo recording and team sign-off.
