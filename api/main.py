"""The API app: sign-in, then one router per tab of the phone app."""

import os

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from order_tracker.users import User

from . import accounts, activity, auth_routes, home, payments, settings
from .common import current_user

# The web build of the app calls the API from another origin. Sign-in is a bearer token,
# not a cookie, so no credentials are allowed across origins.
DEFAULT_WEB_ORIGINS = "http://localhost:8081"


def create_app() -> FastAPI:
    app = FastAPI(title="Expense Tracker API", docs_url="/api/docs", redoc_url=None, openapi_url="/api/openapi.json")
    origins = [o.strip() for o in os.environ.get("APP_WEB_ORIGINS", DEFAULT_WEB_ORIGINS).split(",") if o.strip()]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"],
                       allow_headers=["Authorization", "Content-Type", "X-Timezone"])
    for router in (auth_routes.router, home.router, home.sync_router, payments.router, activity.router,
                   accounts.router, settings.router, settings.public):
        app.include_router(router)

    @app.get("/api/me")
    def me(user: User = Depends(current_user)) -> dict:
        return {"id": user.id, "email": user.email, "name": user.name}

    @app.get("/healthz")
    def health() -> dict:
        return {"ok": True}

    return app


app = create_app()
