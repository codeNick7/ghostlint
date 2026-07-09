from __future__ import annotations
import os
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from tiramasu_engine.db.models import Base


def _db_path() -> Path:
    override = os.environ.get("TIRAMASU_DB_PATH")
    if override:
        p = Path(override).resolve()
    else:
        data_dir = Path.home() / ".tiramasu"
        data_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(data_dir, 0o700)
        p = data_dir / "tiramasu.db"
    # Restrict permissions on the db file after first creation
    if not p.exists():
        p.touch(mode=0o600)
    return p


def _make_engine():
    db_url = f"sqlite:///{_db_path()}"
    return create_engine(db_url, connect_args={"check_same_thread": False})


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
        Base.metadata.create_all(_engine)
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal()
