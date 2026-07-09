from __future__ import annotations
import os
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, field_validator
from tiramasu_engine.scanner import Scanner, ScanConfig
from tiramasu_engine.db.session import get_session
from tiramasu_engine.db.models import ScanRecord
from sqlalchemy import desc

router = APIRouter()

# Simple API key auth for local-only server.
# Key is auto-generated on first run and stored at ~/.tiramasu/api_key.
# Set TIRAMASU_API_KEY env var to override.
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

# Configurable allowed root paths — scans are only permitted under these.
# Defaults to the current user's home directory.
_ALLOWED_ROOTS: list[Path] = [
    Path(p).resolve()
    for p in os.environ.get("TIRAMASU_ALLOWED_ROOTS", str(Path.home())).split(":")
    if p
]


def _load_api_key() -> str:
    env_key = os.environ.get("TIRAMASU_API_KEY")
    if env_key:
        return env_key
    key_path = Path.home() / ".tiramasu" / "api_key"
    if key_path.exists():
        return key_path.read_text().strip()
    import secrets
    key_path.parent.mkdir(mode=0o700, exist_ok=True)
    key = secrets.token_urlsafe(32)
    key_path.write_text(key)
    key_path.chmod(0o600)
    return key


_SERVER_API_KEY: str | None = None


def _get_server_key() -> str:
    global _SERVER_API_KEY
    if _SERVER_API_KEY is None:
        _SERVER_API_KEY = _load_api_key()
    return _SERVER_API_KEY


def _verify_api_key(api_key: str | None = Security(_api_key_header)) -> str:
    if api_key != _get_server_key():
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return api_key


def _validate_repo_path(raw: str) -> Path:
    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="repo_path does not exist")
    if not resolved.is_dir():
        raise HTTPException(status_code=400, detail="repo_path must be a directory")
    if not any(str(resolved).startswith(str(root)) for root in _ALLOWED_ROOTS):
        raise HTTPException(
            status_code=403,
            detail=f"repo_path is outside allowed roots: {[str(r) for r in _ALLOWED_ROOTS]}",
        )
    return resolved


class ScanRequest(BaseModel):
    repo_path: str
    scan_mode: str = "full"
    engines: list[str] | None = None

    @field_validator("scan_mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        if v not in {"full", "quick", "changed"}:
            raise ValueError("scan_mode must be full, quick, or changed")
        return v


class ScanResponse(BaseModel):
    id: str
    repo_path: str
    status: str
    health_score: float | None
    files_scanned: int
    symbols_found: int
    findings_count: int


def _run_scan(repo_path: str, scan_mode: str, engines: list[str] | None) -> None:
    from tiramasu_engine.scanner import ALL_ENGINES
    config = ScanConfig(
        repo_path=Path(repo_path),
        scan_mode=scan_mode,
        engines=engines or [ALL_ENGINES],
    )
    Scanner(config).scan()


@router.post("/scans", response_model=ScanResponse)
async def start_scan(
    request: ScanRequest,
    background_tasks: BackgroundTasks,
    _: str = Security(_verify_api_key),
):
    resolved = _validate_repo_path(request.repo_path)
    background_tasks.add_task(_run_scan, str(resolved), request.scan_mode, request.engines)
    return ScanResponse(
        id="pending",
        repo_path=str(resolved),
        status="running",
        health_score=None,
        files_scanned=0,
        symbols_found=0,
        findings_count=0,
    )


@router.get("/scans", response_model=list[ScanResponse])
def list_scans(limit: int = 20, _: str = Security(_verify_api_key)):
    session = get_session()
    records = session.query(ScanRecord).order_by(desc(ScanRecord.started_at)).limit(limit).all()
    session.close()
    return [
        ScanResponse(
            id=r.id,
            repo_path=r.repo_path,
            status=r.status,
            health_score=r.health_score_overall,
            files_scanned=r.files_scanned,
            symbols_found=r.symbols_found,
            findings_count=len(r.findings),
        )
        for r in records
    ]


@router.get("/scans/{scan_id}", response_model=ScanResponse)
def get_scan(scan_id: str, _: str = Security(_verify_api_key)):
    session = get_session()
    record = session.query(ScanRecord).filter(ScanRecord.id == scan_id).first()
    session.close()
    if not record:
        raise HTTPException(status_code=404, detail="Scan not found")
    return ScanResponse(
        id=record.id,
        repo_path=record.repo_path,
        status=record.status,
        health_score=record.health_score_overall,
        files_scanned=record.files_scanned,
        symbols_found=record.symbols_found,
        findings_count=len(record.findings),
    )
