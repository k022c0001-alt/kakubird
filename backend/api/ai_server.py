"""Custom AI unified FastAPI backend server."""

from __future__ import annotations

import io
import os
import sys
import traceback
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


print("AI_SERVER_FILE_LOADED")

API_DIR = Path(__file__).resolve().parent
BASE_DIR = API_DIR.parent
ROOT_DIR = BASE_DIR.parent
SRC_DIR = BASE_DIR / "src"
PLUGIN_DIR = ROOT_DIR / "plugins"

for path in (ROOT_DIR, BASE_DIR, SRC_DIR, PLUGIN_DIR):
    value = str(path)
    if value not in sys.path:
        sys.path.insert(0, value)


def configure_utf8_streams() -> None:
    """Use UTF-8 on Windows without wrapping an already-compatible stream."""

    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8")
                continue
            except (AttributeError, ValueError, OSError):
                pass

        buffer = getattr(stream, "buffer", None)
        if buffer is not None:
            setattr(sys, stream_name, io.TextIOWrapper(buffer, encoding="utf-8"))


configure_utf8_streams()
load_dotenv(ROOT_DIR / ".env")
load_dotenv(BASE_DIR / ".env", override=False)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma3")
BACKEND_HOST = os.getenv("TO_BACKEND_HOST", "127.0.0.1")
BACKEND_PORT = int(os.getenv("TO_BACKEND_PORT", "8765"))

AI_MEMORY_DIR = BASE_DIR / ".ai_memory"
AI_MEMORY_DIR.mkdir(parents=True, exist_ok=True)

# ProjectBuildServiceとdownload routeが同じ絶対パスを見るための既定値。
PROJECT_ZIP_OUTPUT_ROOT = Path(
    os.getenv("PROJECT_ZIP_OUTPUT_ROOT", str(ROOT_DIR / "generated_zips"))
).expanduser().resolve()
os.environ["PROJECT_ZIP_OUTPUT_ROOT"] = str(PROJECT_ZIP_OUTPUT_ROOT)

app = FastAPI(title="Custom AI Server", version="3.1")

# Viteの開発ポートが5174以降へずれた場合にも対応する。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(?:127\.0\.0\.1|localhost):51\d{2}",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

print("=")
print("🚀 AI Server Boot")
print("=")
print(f"📂 ROOT_DIR   : {ROOT_DIR}")
print(f"📂 BASE_DIR   : {BASE_DIR}")
print(f"📂 SRC_DIR    : {SRC_DIR}")
print(f"📂 PLUGIN_DIR : {PLUGIN_DIR}")
print(f"📦 ZIP_ROOT   : {PROJECT_ZIP_OUTPUT_ROOT}")
print("-------------------------------------------------")
print(f"🤖 OLLAMA_MODEL : {OLLAMA_MODEL}")
print(f"🌐 OLLAMA_URL   : {OLLAMA_BASE_URL}")
print("=")


def safe_include_router(import_path: str, router_name: str = "router") -> bool:
    """Isolate one broken optional route without hiding its traceback."""

    try:
        print(f"[LOAD] {import_path}")
        module = __import__(import_path, fromlist=[router_name])
        route = getattr(module, router_name)
        if route is None:
            raise RuntimeError(f"{router_name} is None")
        app.include_router(route)
        print(f"[OK] {import_path}")
        return True
    except Exception as exc:
        print(f"[ERROR] {import_path}")
        print(f"{type(exc).__name__}: {exc}")
        traceback.print_exc()
        return False


# Existing application routes.
safe_include_router("backend.api.routes_chat")
safe_include_router("backend.api.routes_system")
safe_include_router("backend.api.routes_memory")
safe_include_router("backend.api.routes_sql")
safe_include_router("backend.api.routes_css")
safe_include_router("backend.api.routes_note")
safe_include_router("backend.api.routes_project")

# ProjectBuildServiceが作成したZIPを配信する専用route。
safe_include_router("backend.api.routes_project_download")


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "status": "ok",
        "message": "Custom AI Server Running",
        "ollama_model": OLLAMA_MODEL,
    }


@app.get("/api/system/ping")
async def ping() -> dict[str, str]:
    return {"status": "alive"}


if __name__ == "__main__":
    print(f"🚀 Starting Uvicorn: http://{BACKEND_HOST}:{BACKEND_PORT}")
    uvicorn.run(
        "backend.api.ai_server:app",
        host=BACKEND_HOST,
        port=BACKEND_PORT,
        reload=False,
    )
