from fastapi import APIRouter

from app.api.routes import assessments, auth, catalogue, evidence, frameworks, organizations

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(catalogue.router)
api_router.include_router(organizations.router)
api_router.include_router(frameworks.router)
api_router.include_router(assessments.router)
api_router.include_router(evidence.router)
