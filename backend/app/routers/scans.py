from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from tiramasu_engine.scanner import Scanner, ScanConfig
from tiramasu_engine.db.session import get_session
from tiramasu_engine.db.models import ScanRecord
from sqlalchemy import desc

router = APIRouter()


class ScanRequest(BaseModel):
    repo_path: str
    scan_mode: str = "full"


class ScanResponse(BaseModel):
    id: str
    repo_path: str
    status: str
    health_score: float | None
    files_scanned: int
    symbols_found: int
    findings_count: int


def _run_scan(repo_path: str, scan_mode: str) -> None:
    config = ScanConfig(repo_path=Path(repo_path), scan_mode=scan_mode)
    scanner = Scanner(config)
    scanner.scan()


@router.post("/scans", response_model=ScanResponse)
async def start_scan(request: ScanRequest, background_tasks: BackgroundTasks):
    path = Path(request.repo_path)
    if not path.exists() or not path.is_dir():
        raise HTTPException(status_code=400, detail="repo_path must be an existing directory")

    background_tasks.add_task(_run_scan, request.repo_path, request.scan_mode)
    return ScanResponse(
        id="pending",
        repo_path=request.repo_path,
        status="running",
        health_score=None,
        files_scanned=0,
        symbols_found=0,
        findings_count=0,
    )


@router.get("/scans", response_model=list[ScanResponse])
def list_scans(limit: int = 20):
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
def get_scan(scan_id: str):
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
