"""HTTP API of Extracta.

Run from the repository root:

    uv run --no-sync uvicorn extracta.app:app --app-dir apps/extracta/server
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from extracta.models import ConvertRequest, Envelope
from extracta.service import ExtractaService, ServerSettings

try:  # best effort: read SARVAM_API_KEY and EXTRACTA_* from a local .env file
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

_DEFAULT_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


@lru_cache(maxsize=1)
def get_service() -> ExtractaService:
    return ExtractaService(ServerSettings())


def create_app() -> FastAPI:
    settings = ServerSettings()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # Importing Docling's models and describing every option takes a while;
        # do it before the first request instead of during it.
        await run_in_threadpool(lambda: get_service().describe())
        yield

    app = FastAPI(
        title="Extracta",
        version="1.0",
        description="Document processing on Docling.",
        lifespan=lifespan,
    )
    app.add_middleware(GZipMiddleware, minimum_size=2048)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def revalidate_pages(request: Request, call_next: Any) -> Any:
        # The page must always load the newest UI build; the hashed files
        # under /assets/ can stay cached.
        response = await call_next(request)
        if not request.url.path.startswith(("/api/", "/assets/")):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", **get_service().describe()["server"]}

    @app.get("/api/catalog")
    def catalog() -> dict[str, Any]:
        return get_service().describe()

    @app.post("/api/convert", response_model=Envelope)
    async def convert(
        file: Annotated[UploadFile, File(description="The document to convert.")],
        options: Annotated[str, Form(description="ConvertRequest as JSON.")] = "{}",
    ) -> Envelope:
        try:
            request = ConvertRequest.model_validate(json.loads(options or "{}"))
        except (ValueError, ValidationError) as exc:
            raise HTTPException(
                status_code=422, detail=f"Invalid options: {exc}"
            ) from exc
        service = get_service()
        limit = int(service.settings.max_upload_mb * 1024 * 1024)
        data = await file.read(limit + 1)
        return await run_in_threadpool(
            service.convert, file.filename or "upload", data, request
        )

    @app.get("/api/jobs/{job_id}/files/{path:path}")
    def job_file(job_id: str, path: str) -> FileResponse:
        target = get_service().job_file(job_id, path)
        if target is None:
            raise HTTPException(status_code=404, detail="File not found.")
        return FileResponse(target, filename=target.name)

    web_dist = settings.web_dist or _DEFAULT_WEB_DIST
    if web_dist.is_dir():
        app.mount("/", StaticFiles(directory=web_dist, html=True), name="web")

    return app


app = create_app()
