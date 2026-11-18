# ScholarPulse modular backend structure

The backend is organized by responsibility. `app/main.py` only creates the FastAPI
application, configures middleware, and mounts routers.

```text
backend/app/
├── main.py
├── api/
│   ├── dependencies.py
│   └── routes/
│       ├── auth.py
│       ├── system.py
│       ├── resources.py
│       ├── community.py
│       ├── collections.py
│       ├── ai.py
│       ├── moderation.py
│       └── frontend.py
├── core/
│   ├── config.py
│   └── security.py
├── db/
│   └── session.py
├── models/
│   └── schema.py
├── schemas/
│   ├── auth.py
│   ├── resources.py
│   ├── community.py
│   ├── collections.py
│   ├── ai.py
│   └── moderation.py
└── services/
    ├── rag_service.py
    └── resource_formatter.py
```

- `api/routes/` contains HTTP endpoints grouped by feature.
- `api/dependencies.py` contains shared authentication and authorization dependencies.
- `schemas/` contains request validation models grouped by feature.
- `core/` contains environment configuration and security helpers.
- `db/` owns database connections and schema initialization.
- `models/` contains database model definitions.
- `services/` contains reusable business logic for retrieval and formatting.

The existing Gmail-only registration and email-verification flow is kept in
`api/routes/auth.py`; SMTP configuration remains environment-driven. Keep the
real `.env` file outside shared archives and source control.
