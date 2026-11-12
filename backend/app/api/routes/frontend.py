import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["Frontend"])


@router.get("/", response_class=HTMLResponse)
def serve_frontend():
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )

    idx_path = os.path.join(base_dir, "frontend", "index.html")

    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    return HTMLResponse(
        content="<h1>ScholarPulse MS-3 API Server Running</h1>"
        "<p>Visit <a href='/docs'>/docs</a> for OpenAPI UI.</p>"
    )