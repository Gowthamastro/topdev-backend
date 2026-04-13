from fastapi import APIRouter
from app.api.v1 import auth, jobs, candidates, clients, admin, payments, analytics, assessments, proctor, config, otp

api_router = APIRouter()

api_router.include_router(auth.router)
api_router.include_router(jobs.router)
api_router.include_router(candidates.router)
api_router.include_router(clients.router)
api_router.include_router(admin.router)
api_router.include_router(payments.router)
api_router.include_router(analytics.router)
api_router.include_router(assessments.router)
api_router.include_router(proctor.router)
api_router.include_router(config.router)
api_router.include_router(otp.router)
