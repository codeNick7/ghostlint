from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import scans

app = FastAPI(
    title="ghostlint API",
    description="Repository Health Intelligence Platform",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(scans.router, prefix="/api/v1")


@app.get("/health")
def health_check():
    return {"status": "ok", "version": "0.1.0"}
