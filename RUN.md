# Run ScholarPulse (backend + frontend, one command)
```bash
cp .env.example .env
docker compose up --build
```
Website: http://localhost:8000/   API docs: http://localhost:8000/docs   Health: http://localhost:8000/api/v1/health
Demo login: sam.green@university.edu / ScholarPulse!2026

Stop: `docker compose down`   Reset database: `docker compose down -v`
The backend serves the frontend (frontend/index.html), so there is no separate frontend server.
