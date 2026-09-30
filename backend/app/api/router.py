from fastapi import APIRouter

from app.api.routes import admin, auth, billing, bidding, guards, lookups, shamoos, shifts

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(lookups.router)
api_router.include_router(admin.router)
api_router.include_router(guards.router)
api_router.include_router(shamoos.router)
api_router.include_router(bidding.router)
api_router.include_router(shifts.router)
api_router.include_router(billing.router)
