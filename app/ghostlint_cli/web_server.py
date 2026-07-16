from __future__ import annotations
import http.server
import os
import shutil
import socket
import stat
import threading
import webbrowser
from pathlib import Path


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def prepare_report_dir(html_content: str) -> tuple[Path, Path]:
    """Write *html_content* into a dedicated temp directory readable only by
    the current user. Returns (serve_dir, html_path)."""
    import tempfile
    serve_dir = Path(tempfile.mkdtemp(prefix="ghostlint_report_"))
    # Restrict to owner only — no world or group read
    os.chmod(serve_dir, stat.S_IRWXU)
    html_path = serve_dir / "report.html"
    html_path.write_text(html_content, encoding="utf-8")
    return serve_dir, html_path


def serve_and_open(
    serve_dir: Path,
    html_path: Path,
    open_browser: bool = True,
) -> tuple[int, str, threading.Thread]:
    """Serve only *html_path* (located inside *serve_dir*) on a random
    localhost port.

    Security hardening applied:
    - Binds to 127.0.0.1 only.
    - Rejects any request whose Host header is not 127.0.0.1:<port>
      (blocks DNS-rebinding attacks).
    - Only serves the single known filename; everything else returns 404.
    - Directory listings are disabled.

    Returns (port, url, server_thread). The thread is a daemon and dies
    with the main process. Call cleanup_report_dir(serve_dir) when done.
    """
    port = _find_free_port()
    filename = html_path.name
    allowed_host = f"127.0.0.1:{port}"

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            # DNS-rebinding guard: reject unexpected Host headers
            host = self.headers.get("Host", "")
            if host and host != allowed_host:
                self._send_error(403, "Forbidden")
                return

            # Only serve the one known file
            if self.path not in (f"/{filename}", "/"):
                self._send_error(404, "Not Found")
                return

            try:
                data = html_path.read_bytes()
            except OSError:
                self._send_error(500, "Internal Server Error")
                return

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            # Prevent the page from making credentialed cross-origin requests
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            # The HTML report uses inline styles, inline scripts, and loads
            # Chart.js from cdn.jsdelivr.net (with SRI hash for integrity).
            # connect-src 'none' blocks any JS fetch/XHR to external servers,
            # which is the useful XSS exfiltration backstop even with unsafe-inline.
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; "
                "script-src 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'unsafe-inline'; "
                "img-src data:; "
                "connect-src 'none';",
            )
            self.end_headers()
            self.wfile.write(data)

        def do_HEAD(self):
            self.do_GET()

        def _send_error(self, code: int, message: str):
            body = message.encode()
            self.send_response(code)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass  # silence access log

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    url = f"http://127.0.0.1:{port}/{filename}"
    if open_browser:
        webbrowser.open(url)

    return port, url, thread


def cleanup_report_dir(serve_dir: Path) -> None:
    shutil.rmtree(serve_dir, ignore_errors=True)
