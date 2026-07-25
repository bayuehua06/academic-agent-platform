"""API 路由聚合。"""

from fastapi import APIRouter

from app.api import auth, drafts, notebook, projects, zotero

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(projects.router)
api_router.include_router(drafts.router)
api_router.include_router(zotero.router)
api_router.include_router(notebook.router)
