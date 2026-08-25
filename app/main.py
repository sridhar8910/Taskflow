import os
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.dependencies import get_current_user
from app.middleware import MetricsMiddleware
from app.models.user import User
from app.routers import auth, notifications, ops, projects, tasks

app = FastAPI(
    title="TaskFlow",
    description="Task Management API with background notifications and Redis caching.",
    version="0.1.0",
)

# ── Middleware ─────────────────────────────────────────────────────────────────
app.add_middleware(MetricsMiddleware)

# ── Routers ───────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(tasks.router)
app.include_router(notifications.router)
app.include_router(ops.router)

# Also mount under /api/v1 for external API client compatibility
app.include_router(auth.router, prefix="/api/v1")
app.include_router(projects.router, prefix="/api/v1")
app.include_router(tasks.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(ops.router, prefix="/api/v1")

# ── Static Files (Frontend UI) ────────────────────────────────────────────────
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

    @app.get("/app", tags=["ui"])
    async def serve_ui():
        return FileResponse(os.path.join(frontend_dir, "index.html"))

    @app.get("/style.css", include_in_schema=False)
    async def serve_css():
        return FileResponse(os.path.join(frontend_dir, "style.css"))

    @app.get("/app.js", include_in_schema=False)
    async def serve_js():
        return FileResponse(os.path.join(frontend_dir, "app.js"))


# ── Root ──────────────────────────────────────────────────────────────────────
@app.get("/", tags=["root"])
async def root():
    if os.path.exists(os.path.join(frontend_dir, "index.html")):
        return FileResponse(os.path.join(frontend_dir, "index.html"))
    return {"status": "ok", "env": settings.app_env, "docs": "/docs"}



# ── Protected stub used in auth tests ─────────────────────────────────────────
@app.get("/me", tags=["auth"])
async def me(current_user: User = Depends(get_current_user)) -> dict:
    return {"id": str(current_user.id), "email": current_user.email}

