from __future__ import annotations
import json
from datetime import datetime
from sqlalchemy import String, Float, Integer, DateTime, ForeignKey, Text, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ScanRecord(Base):
    __tablename__ = "scans"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    repo_path: Mapped[str] = mapped_column(String, nullable=False)
    scan_mode: Mapped[str] = mapped_column(String, default="full")
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String, default="running")
    health_score_overall: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_score_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    files_scanned: Mapped[int] = mapped_column(Integer, default=0)
    symbols_found: Mapped[int] = mapped_column(Integer, default=0)

    findings: Mapped[list[FindingRecord]] = relationship(
        "FindingRecord", back_populates="scan", cascade="all, delete-orphan"
    )


class FindingRecord(Base):
    __tablename__ = "findings"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    scan_id: Mapped[str] = mapped_column(String, ForeignKey("scans.id"), nullable=False)
    category: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    line_start: Mapped[int] = mapped_column(Integer, default=0)
    line_end: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    risk: Mapped[str] = mapped_column(String, default="low")
    effort: Mapped[str] = mapped_column(String, default="minutes")
    benefit: Mapped[str] = mapped_column(Text, default="")
    autofix_available: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")

    scan: Mapped[ScanRecord] = relationship("ScanRecord", back_populates="findings")

    def evidence_list(self) -> list[dict]:
        return json.loads(self.evidence_json)
