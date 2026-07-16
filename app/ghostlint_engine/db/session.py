from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from ghostlint_engine.db.models import Base


def _db_path() -> Path:
    override = os.environ.get("GHOSTLINT_DB_PATH")
    if override:
        p = Path(override).resolve()
    else:
        data_dir = Path.home() / ".ghostlint"
        data_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(data_dir, 0o700)
        p = data_dir / "ghostlint.db"
    # Restrict permissions on the db file after first creation
    if not p.exists():
        p.touch(mode=0o600)
    return p


def _make_engine():
    db_url = f"sqlite:///{_db_path()}"
    return create_engine(db_url, connect_args={"check_same_thread": False})


_engine = None
_SessionLocal = None


def _migrate(engine) -> None:
    """Add columns introduced after initial schema creation (SQLite-compatible)."""
    with engine.connect() as conn:
        existing = {
            row[1]
            for row in conn.execute(
                __import__("sqlalchemy").text("PRAGMA table_info(scans)")
            )
        }
        if "commit_sha" not in existing:
            conn.execute(
                __import__("sqlalchemy").text(
                    "ALTER TABLE scans ADD COLUMN commit_sha VARCHAR(40)"
                )
            )
            conn.commit()


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
        Base.metadata.create_all(_engine)
        _migrate(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal()
