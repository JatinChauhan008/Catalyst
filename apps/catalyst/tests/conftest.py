"""Fixtures: a fake Sarvam Document Intelligence server and the Catalyst service."""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
import uuid
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))


@dataclass
class FakeSarvam:
    """Records Digitise jobs and answers with one block per page.

    The text block covers the top part of the page image and holds `lines`.
    Each entry of `tables` adds a table block: a normalized box and its HTML.
    """

    base_url: str = ""
    lines: tuple[str, ...] = ("SARVAM FAKE LINE ONE", "SARVAM FAKE LINE TWO")
    tables: list[tuple[tuple[float, float, float, float], str]] = field(
        default_factory=list
    )
    jobs: dict[str, dict] = field(default_factory=dict)
    submissions: list[dict] = field(default_factory=list)
    translations: list[dict] = field(default_factory=list)
    # The next requests to /translate that get "429 Too Many Requests".
    rate_limited: int = 0

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.post("/doc-ai/v1/job/digitise", status_code=201)
        async def digitise(request: Request) -> JSONResponse:
            if request.headers.get("api-subscription-key") != "test-key":
                return JSONResponse(
                    {"title": "Forbidden", "detail": "bad key"}, status_code=403
                )
            form = await request.form()
            upload = form["file"]
            archive = zipfile.ZipFile(io.BytesIO(await upload.read()))
            sizes = [
                Image.open(io.BytesIO(archive.read(name))).size
                for name in sorted(archive.namelist())
            ]
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {"sizes": sizes, "polls": 0}
            self.submissions.append(
                {k: v for k, v in form.items() if k != "file"} | {"pages": len(sizes)}
            )
            return JSONResponse(
                {"job_id": job_id, "status": "pending", "run_id": "r1"}, status_code=201
            )

        @app.get("/doc-ai/v1/job/{job_id}/status")
        def status(job_id: str) -> dict:
            job = self.jobs[job_id]
            job["polls"] += 1
            if job["polls"] < 2:
                return {"job_id": job_id, "status": "Running"}
            pages = len(job["sizes"])
            return {
                "job_id": job_id,
                "status": "Completed",
                "usage": {
                    "pages_total": pages,
                    "pages_processed": pages,
                    "pages_succeeded": pages,
                    "pages_failed": 0,
                },
            }

        @app.post("/translate")
        async def translate(request: Request) -> JSONResponse:
            # "EN: <input>"; an input with "FAIL" fails; "DROP" loses the numbers.
            if self.rate_limited > 0:
                self.rate_limited -= 1
                return JSONResponse(
                    {"error": {"message": "Rate limit exceeded"}},
                    status_code=429,
                    headers={"Retry-After": "1"},
                )
            body = await request.json()
            self.translations.append(body)
            text = body["input"]
            if "FAIL" in text:
                return JSONResponse({"error": {"message": "bad"}}, status_code=400)
            if "DROP" in text:
                text = "".join(char for char in text if not char.isdigit())
            source = body["source_language_code"]
            return JSONResponse(
                {
                    "request_id": "t1",
                    "translated_text": f"EN: {text}",
                    "source_language_code": "hi-IN" if source == "auto" else source,
                }
            )

        @app.get("/doc-ai/v1/job/{job_id}/download-url")
        def download_url(job_id: str) -> dict:
            return {
                "method": "GET",
                "url": f"{self.base_url}/download/{job_id}",
                "expires_at": "2099-01-01T00:00:00Z",
            }

        @app.get("/download/{job_id}")
        def download(job_id: str) -> Response:
            # The archive layout of a real Digitise result (checked 2026-10).
            pages = []
            for number, (width, height) in enumerate(
                self.jobs[job_id]["sizes"], start=1
            ):
                text_box = (0.1, 0.05, 0.9, 0.25)
                image_box = (0.0, 0.5, 1.0, 1.0)
                pages.append(
                    {
                        "page_num": number,
                        "image_width": width,
                        "image_height": height,
                        "blocks": [
                            _fake_block(
                                "paragraph",
                                "\n".join(self.lines),
                                text_box,
                                width,
                                height,
                            ),
                            _fake_block("image", "", image_box, width, height),
                            *(
                                _fake_block("table", html, box, width, height)
                                for box, html in self.tables
                            ),
                        ],
                    }
                )
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                document = {
                    "filename": "pages.zip",
                    "page_count": len(pages),
                    "pages": pages,
                }
                archive.writestr("pages.zip/pages.json", json.dumps(document))
                archive.writestr("manifest.json", json.dumps({"status": "completed"}))
            return Response(buffer.getvalue(), media_type="application/zip")

        return app


def _fake_block(
    tag: str, text: str, box: tuple[float, ...], width: int, height: int
) -> dict:
    x0, y0, x1, y1 = box
    return {
        "block_id": "b",
        "coordinates": {
            "x1": x0 * width,
            "y1": y0 * height,
            "x2": x1 * width,
            "y2": y1 * height,
        },
        "bbox_norm": list(box),
        "layout_tag": tag,
        "confidence": 0.9,
        "reading_order": 1,
        "text": text,
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def fake_sarvam() -> Iterator[FakeSarvam]:
    fake = FakeSarvam()
    port = _free_port()
    fake.base_url = f"http://127.0.0.1:{port}"
    server = uvicorn.Server(
        uvicorn.Config(fake.app(), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield fake
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(scope="session")
def service(tmp_path_factory: pytest.TempPathFactory):
    from catalyst.service import CatalystService, ServerSettings

    return CatalystService(ServerSettings(data_dir=tmp_path_factory.mktemp("catalyst")))
