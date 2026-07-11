from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings, validate_startup_settings
from app.core.middleware import add_request_middleware
from app.services.readiness import build_readiness_report, readiness_status_code


def create_app() -> FastAPI:
    settings = get_settings()
    validate_startup_settings(settings)
    app = FastAPI(title=settings.app_name, version="0.1.0")
    add_request_middleware(app, settings)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(router, prefix="/api/v1")

    @app.get("/health", tags=["system"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @app.get("/ready", tags=["system"])
    def ready(response: Response) -> dict:
        report = build_readiness_report(settings)
        response.status_code = readiness_status_code(report)
        return report

    return app


app = create_app()
