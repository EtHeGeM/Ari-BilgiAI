from fastapi import APIRouter

from app.api.v1.endpoints import admin, auth, orders, users, vendor_panel, vendors

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(orders.router, prefix="/orders", tags=["orders"])
api_router.include_router(vendors.router, prefix="/vendors", tags=["vendors"])
api_router.include_router(vendor_panel.router, prefix="/vendor-panel", tags=["vendor-panel"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
