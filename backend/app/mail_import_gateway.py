"""Source candidate for a TLS-fronted ingestion-only gateway, never a deploy script.

Uses the existing primary-DB dependency, but not app.main, its lifespan, background
workers, or owner APIs. TLS termination and network exposure require a separate
approved deployment. No startup DDL or migrations are performed here.
"""
from fastapi import FastAPI

from app.api.routes.mail_import import device_router


app = FastAPI(title="DPMS Inbox ingestion", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(device_router, prefix="/api/mail-import")
