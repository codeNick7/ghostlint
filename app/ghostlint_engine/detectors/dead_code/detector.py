from __future__ import annotations
import re
from pathlib import Path
from ghostlint_engine.ast_engine.base import SymbolDef
from ghostlint_engine.detectors.base import BaseDetector
from ghostlint_engine.indexer import MAX_FILE_BYTES
from ghostlint_engine.graph.context import AnalysisContext
from ghostlint_engine.models.findings import (
    DetectionCategory, Evidence, EffortLevel, Finding, RiskLevel,
)

# Symbols that are valid entry points and should never be flagged
_SKIP_NAMES = {
    "main", "__init__", "__new__", "__call__", "__del__",
    "__str__", "__repr__", "__len__", "__iter__", "__next__",
    "__enter__", "__exit__", "__getitem__", "__setitem__", "__delitem__",
    "__contains__", "__eq__", "__hash__", "__lt__", "__le__", "__gt__", "__ge__",
    "__add__", "__sub__", "__mul__", "__truediv__", "__floordiv__", "__mod__",
    "__bool__", "__int__", "__float__", "__bytes__", "__format__",
    "setUp", "tearDown", "setUpClass", "tearDownClass",
    "app", "router",  # common FastAPI / Flask entry points
    # Inner closure returned by decorator factories (e.g. def require_permission(...)
    # contains def decorator(fn): ... which is the actual wrapper returned to callers).
    # Static analysis cannot trace the return-value usage, so it always appears dead.
    "decorator", "wrapper", "inner",
    # Next.js / React framework convention functions — auto-discovered by the
    # framework's file-based router, never imported explicitly.
    "generateStaticParams", "generateMetadata",
    # Next.js Metadata Route handlers (robots.ts / sitemap.ts) — return route
    # config consumed by the framework, never called directly.
    "robots", "sitemap",
    # Playwright global setup/teardown — invoked by the runner by name.
    "globalSetup", "globalTeardown",
}

# Next.js App Router API route handler HTTP methods (in route.ts/route.js files).
# These are called by the framework's request dispatcher, not imported.
_ROUTE_HANDLER_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}

# File path patterns whose functions are called by external frameworks at runtime.
# Key: path segment that must appear in the file path.
# Value: set of function names that are framework-managed entry points in that context.
_PATH_ENTRY_POINTS: dict[str, set[str]] = {
    "alembic/versions": {"upgrade", "downgrade"},
    "migrations/versions": {"upgrade", "downgrade"},
    "migrations": {"upgrade", "downgrade"},
}

# Decorator patterns that indicate the symbol is a framework-managed entry point.
# Matched as substring so "@router.get('/path')" matches "@router.get".
_ENTRY_DECORATORS = {
    # FastAPI / Starlette
    "@app.get", "@app.post", "@app.put", "@app.delete", "@app.patch",
    "@app.head", "@app.options", "@app.trace", "@app.websocket",
    "@app.on_event", "@app.middleware", "@app.exception_handler",
    "@router.get", "@router.post", "@router.put", "@router.delete",
    "@router.patch", "@router.head", "@router.options", "@router.websocket",
    # Flask / Blueprint
    "@app.route", "@bp.route", "@blueprint.route",
    "@app.before_request", "@app.after_request", "@app.teardown_request",
    "@app.teardown_appcontext", "@app.errorhandler", "@app.context_processor",
    "@app.template_filter", "@app.template_global",
    "@bp.before_request", "@bp.after_request", "@bp.errorhandler",
    "@login_required", "@permission_required",  # Flask-Login / Django
    # Django
    "@csrf_exempt", "@csrf_protect",
    "@require_http_methods", "@require_GET", "@require_POST", "@require_safe",
    "@cache_page", "@cache_control", "@never_cache",
    "@receiver",            # signal handler — called by Django's signal dispatcher
    "@admin.register",      # registers a ModelAdmin with Django admin
    "@transaction.atomic",
    "@action",              # Django REST Framework viewset action
    "@api_view",            # DRF function-based view
    # Celery
    "@shared_task", "@app.task", "@celery.task", "@periodic_task",
    "@task",
    # APScheduler / schedule / rq
    "@scheduler.scheduled_job", "@job",
    # SQLAlchemy event listeners
    "@event.listens_for",
    # Click / Typer
    "@click.command", "@click.group", "@click.pass_context", "@click.pass_obj",
    "@app.command", "@typer.command",
    # pytest
    "@pytest.fixture", "@pytest.mark",
    # Python built-ins that fundamentally change how a symbol is used
    "@property", "@staticmethod", "@classmethod",
    "@functools.lru_cache", "@functools.cache", "@functools.cached_property",
    "@functools.wraps",
    # Pydantic
    "@validator", "@field_validator", "@model_validator", "@root_validator",
    "@computed_field",
    # dataclasses / attrs
    "@dataclass",
    # Abstract base classes
    "@abstractmethod", "@abc.abstractmethod",
    # Overrides (may be called polymorphically)
    "@override",
}

# Base class names that indicate a class is instantiated or called by a
# framework at runtime — not through explicit construction in application code.
_ENTRY_BASE_CLASSES = {
    # Django ORM
    "Model",                        # models.Model
    "Migration",                    # database migration — run by manage.py migrate
    "AppConfig",                    # apps.py — loaded by INSTALLED_APPS
    "BaseCommand",                  # management command — invoked by manage.py
    # Django views (class-based)
    "View", "TemplateView", "RedirectView",
    "ListView", "DetailView",
    "CreateView", "UpdateView", "DeleteView",
    "FormView", "BaseFormView",
    "ArchiveIndexView", "YearArchiveView", "MonthArchiveView", "DayArchiveView",
    # Django admin
    "ModelAdmin", "TabularInline", "StackedInline", "InlineModelAdmin",
    "AdminSite",
    # Django forms
    "Form", "ModelForm", "BaseFormSet", "BaseModelFormSet",
    # Django REST Framework
    "APIView", "GenericAPIView",
    "ListAPIView", "CreateAPIView", "RetrieveAPIView",
    "UpdateAPIView", "DestroyAPIView",
    "ListCreateAPIView", "RetrieveUpdateAPIView", "RetrieveDestroyAPIView",
    "RetrieveUpdateDestroyAPIView",
    "ViewSet", "ModelViewSet", "ReadOnlyModelViewSet",
    "GenericViewSet",
    "Serializer", "ModelSerializer", "ListSerializer",
    "HyperlinkedModelSerializer", "HyperlinkedSerializer",
    "BasePermission",               # DRF permission class
    "BaseAuthentication",           # DRF auth class
    "BaseThrottle",                 # DRF throttle class
    "BaseRenderer", "BaseParser",   # DRF renderers/parsers
    "BaseFilterBackend",            # DRF filter backend
    # Django signals / middleware
    "MiddlewareMixin",
    # Django test
    "TestCase", "SimpleTestCase", "TransactionTestCase", "LiveServerTestCase",
    # SQLAlchemy / Flask-SQLAlchemy
    "Base",                         # declarative base
    "DeclarativeBase", "DeclarativeBaseNoMeta",
    "MappedAsDataclass",
    # Flask
    "MethodView", "View",           # Flask class-based views
    # Pydantic
    "BaseModel", "BaseSettings",    # always constructed from external data
    # Celery
    "Task",                         # custom Celery task class
    # Python stdlib patterns used by frameworks
    "ABC",                          # abstract base — never directly instantiated
    "Enum", "IntEnum", "StrEnum", "Flag", "IntFlag",  # discovered by name
    "TypedDict",                    # used by type checkers, not directly called
    "Protocol",                     # structural subtyping — never instantiated
    "NamedTuple",
    # Click
    "MultiCommand", "Group",
}


def _is_entry_point(sym: SymbolDef) -> bool:
    if sym.name in _SKIP_NAMES:
        return True
    if sym.name.startswith("test_") or sym.name.startswith("Test"):
        return True
    # Dunder methods
    if sym.name.startswith("__") and sym.name.endswith("__"):
        return True
    # Decorated with a known entry-point decorator
    for dec in sym.decorators:
        for pattern in _ENTRY_DECORATORS:
            if pattern in dec:
                return True
    # Class inherits from a framework base that is instantiated/discovered at runtime
    if sym.kind == "class" and any(b in _ENTRY_BASE_CLASSES for b in sym.base_classes):
        return True
    # Framework-managed functions called by external tools at runtime (e.g. Alembic)
    normalized = sym.file_path.replace("\\", "/")

    # --- Next.js / React framework entry points (JS/TS) ---
    # 1. API route handlers: HTTP method functions (GET/POST/...) in route.ts/tsx.
    #    Called by the Next.js request dispatcher, never imported.
    if sym.name in _ROUTE_HANDLER_METHODS and "/route." in normalized:
        return True
    # 2. Page / layout components under an app/ directory are auto-discovered by
    #    the Next.js App Router file convention. Their default-export component
    #    (often the only function in the file) is rendered by the router.
    if sym.kind == "function" and "/app/" in normalized:
        stem = Path(normalized).stem
        if stem in ("page", "layout", "template", "default", "error",
                     "loading", "not-found", "opengraph-image", "twitter-image"):
            return True
    # 3. React component default exports often carry the page name; if a function
    #    is the default export of a Next.js page/layout file, treat as entry point.
    if sym.is_exported and sym.kind == "function" and "/app/" in normalized:
        app_seg = normalized.split("/app/", 1)[1]
        # top-level segment is a route dir; the file is page.tsx/layout.tsx etc.
        if app_seg.endswith(("page.tsx", "page.ts", "page.jsx", "page.js",
                              "layout.tsx", "layout.ts", "layout.jsx", "layout.js")):
            return True

    for path_segment, names in _PATH_ENTRY_POINTS.items():
        if path_segment in normalized and sym.name in names:
            return True

    # --- Test files (JS/TS) ---
    # Helper functions defined inside test files (.spec./.test./tests/) are
    # invoked within describe()/it()/test() blocks that the AST may not fully
    # resolve. Treat non-test-named functions in test files as entry points to
    # avoid flagging legitimate test helpers as dead code.
    is_test_file = (
        ".test." in normalized or ".spec." in normalized
        or normalized.startswith("tests/") or "/tests/" in normalized
        or "/e2e/" in normalized or normalized.endswith(("-e2e/", "/e2e"))
        or "/subscription-e2e/" in normalized or "/ask-ai-tests/" in normalized
    )
    if is_test_file and sym.kind in ("function", "arrow_function"):
        return True

    return False


def _confidence(sym: SymbolDef) -> float:
    score = 0.5

    # Private symbols unreferenced anywhere = very likely dead
    if sym.is_private:
        score += 0.3

    # Free functions (not methods) with no decorators = unlikely to be overrides or hooks
    if sym.kind == "function" and not sym.decorators:
        score += 0.15

    # Arrow functions / lambdas assigned to a variable
    if sym.kind == "arrow_function":
        score += 0.1

    # Methods could be overrides or called via polymorphism — lower confidence
    if sym.kind == "method":
        score -= 0.15

    # Classes might be instantiated dynamically (reflection, factories)
    if sym.kind == "class":
        score -= 0.1

    return round(min(max(score, 0.0), 1.0), 2)


def _risk(sym: SymbolDef) -> RiskLevel:
    if sym.is_private:
        return RiskLevel.LOW
    if sym.kind in ("function", "arrow_function"):
        return RiskLevel.LOW
    if sym.kind == "method":
        return RiskLevel.MEDIUM
    return RiskLevel.MEDIUM


# Python: "from X import ..." or "import X"
_PY_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+(\.+[\w.]*|[\w][\w.]*)\s+import|import\s+([\w][\w.]*))",
    re.MULTILINE,
)

# JS/TS: import ... from 'path' / import('path') / require('path')
# Captures the quoted module path string (group 1).
# Handles:
#   - Relative:      ./utils  ../components/Button
#   - Package:       react  next/link  @radix-ui/react-dialog
#   - Path aliases:  @/components/ui/button  ~/lib/utils  #/utils  src/utils
_JS_IMPORT_RE = re.compile(
    r"""(?:from\s+|import\s*\(|require\s*\()['"](\.{1,2}/[^'"]+|[@~#]/[^'"]+|@[\w][\w/.-]*|[\w][\w/.-]*)['"]\)?""",
    re.MULTILINE,
)

# File stems that are always entry points — never flag these as unused modules.
_MODULE_ENTRY_POINT_STEMS = {
    # Python
    "__init__", "main", "manage", "settings", "config", "wsgi", "asgi",
    "conftest", "setup", "app", "server", "celery", "worker", "tasks",
    "urls", "admin", "signals", "middleware",  # Django
    "entrypoint", "entry_point", "run", "start",
    "env",  # Alembic env.py — invoked by the alembic CLI, not imported
    # JS/TS
    "index",         # index.ts/js is always the package entry point
    "next.config",   # Next.js config files
    "tailwind.config", "postcss.config", "jest.config", "vitest.config",
    "vite.config", "webpack.config", "babel.config", "eslint.config",
    "tsconfig", "playwright.config", "capacitor.config",
    "globals",       # globals.css / globals.ts
    "layout",        # Next.js layout.tsx
    "page",          # Next.js page.tsx
    "route",         # Next.js API route.ts
    "error",         # Next.js error.tsx
    "loading",       # Next.js loading.tsx
    "not-found",     # Next.js not-found.tsx
    "template",      # template.tsx (Next.js App Router)
    "default",       # Next.js default.tsx
    # Next.js App Router convention files (auto-discovered by the framework,
    # never imported via an import statement)
    "robots", "sitemap", "manifest", "icon", "apple-icon", "favicon",
    "opengraph-image", "twitter-image", "linkedin-image",
}

# Path segments that indicate a file is loaded dynamically by a framework.
_DYNAMIC_PATH_SEGMENTS = {
    "alembic/versions", "migrations/versions", "migrations",
    "alembic", "scripts", "fixtures", "seeds",
    # Playwright/Alembic standalone scripts invoked by CLI, not imported
    "ask-ai-tests", "compatibility-tests", "subscription-e2e",
    "dooradarshika-upgrade-tests",
}

# Stems of framework-generated files — present in the source tree but produced
# by tooling at build/runtime, never authored or imported as source modules.
_GENERATED_STEMS = {
    "next-env",          # next-env.d.ts — Next.js auto-generated type decls
    "_buildmanifest",    # Next.js build output
    "_ssgmanifest",      # Next.js build output
    "cordova",           # Cordova runtime-generated
    "cordova_plugins",   # Cordova runtime-generated
}

# Bundler output filenames contain a content hash — 8+ hex chars in the stem.
# e.g. "5333.e1ed8bd7bd6b4bbb.js", "layout-cde9c4d7a42012df.js"
# These are webpack/Metro/Vite chunks, not source modules.
_CONTENT_HASH_RE = re.compile(r"[0-9a-f]{8,}", re.IGNORECASE)

# Path substrings that mark a file as non-source (generated artifacts, mobile
# build output, templates copied rather than imported).
_NON_SOURCE_PATH_PARTS = (
    "/templates/",        # scaffold templates — copied, never imported
    "public/_next/",      # Next.js exported static output (mobile bundle)
    "public/cordova",     # Cordova runtime files copied to mobile bundle
    # Tooling hooks invoked by config, never imported as a module
    # (e.g. .claude/settings.local.json "command": "python3 .../hooks/x.py")
    ".claude/hooks/",
    # Legacy backup directories — copies of source trees kept for reference,
    # not active code. Both "frontend-backup/" and "-backup/" patterns.
    "-backup/",
    "frontend-backup/",
    # shadcn/ui component library files. shadcn installs Radix-UI primitive
    # wrappers as local source under components/ui/. Not all installed components
    # are actively imported — this is the design-system-as-code adoption pattern,
    # not dead code. Suppress both module and function findings for this directory.
    "components/ui/",
)

# Extensions of non-source config/script files that may reference modules by
# name (e.g. deployment scripts, CI config, Dockerfiles, JSON configs). These
# files are not parsed by the indexer (only .py/.js/.ts/.tsx are), but they can
# invoke modules via `python -m pkg.mod`, `from pkg.mod import x`, or
# `import pkg.mod` — so scanning them prevents false-positive "unused module"
# findings for files wired up outside an import statement.
_NON_SOURCE_SCAN_EXTS = {
    ".sh", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".json", ".mk",
    ".mkd", ".md",
}
_NON_SOURCE_SCAN_NAMES = {
    "makefile", "dockerfile", "procfile", "justfile",
}
_NON_SOURCE_SCAN_SKIP_DIRS = {
    ".git", ".svn", "node_modules", ".venv", "venv", "__pycache__",
    "dist", "build", ".next", ".mypy_cache", ".pytest_cache",
}

# Matches module references in non-source files:
#   python -m app.db.seed_catalog        → group "app.db.seed_catalog"
#   python3 -m app.db.seed_catalog       → group "app.db.seed_catalog"
#   from app.db.seed_catalog import x    → group "app.db.seed_catalog"
#   import app.db.seed_catalog           → group "app.db.seed_catalog"
_NON_SOURCE_MODULE_RE = re.compile(
    r"(?:python[23]?\s+-m\s+|from\s+|import\s+)([a-zA-Z_][\w.]*)",
)


def _scan_non_source_module_refs(repo_path: Path) -> set[str]:
    """Scan non-source config/script files for module references.

    Returns a set of dotted module paths referenced via ``python -m``,
    ``from ... import``, or ``import ...`` in shell scripts, Dockerfiles,
    CI configs, etc. Used to suppress false-positive unused-module findings for
    modules that are invoked by deployment/CI tooling rather than imported by
    application code.
    """
    referenced: set[str] = set()
    try:
        for file_path in repo_path.rglob("*"):
            if not file_path.is_file():
                continue
            if any(part in _NON_SOURCE_SCAN_SKIP_DIRS for part in file_path.parts):
                continue
            name_lower = file_path.name.lower()
            ext = file_path.suffix.lower()
            if ext not in _NON_SOURCE_SCAN_EXTS and name_lower not in _NON_SOURCE_SCAN_NAMES:
                continue
            if file_path.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                text = file_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for m in _NON_SOURCE_MODULE_RE.finditer(text):
                module = m.group(1)
                parts = module.split(".")
                for i in range(len(parts)):
                    referenced.add(".".join(parts[i:]))
    except OSError:
        pass
    return referenced


def _build_referenced_module_keys(context: AnalysisContext) -> set[str]:
    """
    Scan all files for import statements and return a set of all module
    name segments that are referenced.

    We collect every suffix of every dotted/slashed path so that an import
    like 'from myapp.utils.helpers import x' or
    'import { x } from "../utils/helpers"'
    registers 'myapp.utils.helpers', 'utils.helpers', and 'helpers' — this
    lets us match against any file whose repo-relative path ends in any of
    those segments.
    """
    referenced: set[str] = set()

    for file_info in context.files:
        content = file_info.content

        if file_info.language == "python":
            for m in _PY_IMPORT_RE.finditer(content):
                raw = m.group(1) or m.group(2) or ""
                # Strip leading dots (relative markers: ".utils", "..db.session")
                module = raw.lstrip(".")
                if not module:
                    continue
                parts = module.split(".")
                for i in range(len(parts)):
                    referenced.add(".".join(parts[i:]))

        elif file_info.language in ("javascript", "typescript"):
            for m in _JS_IMPORT_RE.finditer(content):
                raw = m.group(1) or ""
                # Normalize path separators and strip extensions
                norm = raw.replace("\\", "/")
                for ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"):
                    norm = norm.removesuffix(ext)
                # Strip trailing /index
                if norm.endswith("/index"):
                    norm = norm[: -len("/index")]
                # Strip path alias prefixes: @/ ~/  #/  (Next.js, Vite, Nuxt)
                # e.g. "@/components/ui/button" → "components/ui/button"
                for alias_prefix in ("@/", "~/", "#/", "src/"):
                    if norm.startswith(alias_prefix):
                        norm = norm[len(alias_prefix):]
                        break
                # Strip relative markers ./ and ../
                while norm.startswith("../"):
                    norm = norm[3:]
                if norm.startswith("./"):
                    norm = norm[2:]
                if not norm:
                    continue
                # Register all path-segment suffixes in both dotted and slash form
                slash_parts = [p for p in norm.split("/") if p]
                for i in range(len(slash_parts)):
                    referenced.add("/".join(slash_parts[i:]))
                    referenced.add(".".join(slash_parts[i:]))

    return referenced


def _is_module_entry_point(relative_path: str, content: str | None = None) -> bool:
    """Return True if this file should never be flagged as an unused module.

    ``content`` (the file's source text) is optional; when provided for a
    Python file, a top-level ``if __name__ == "__main__":`` block marks the
    file as a runnable entry point — it is executed directly (``python foo.py``
    / ``python -m pkg.foo``) rather than imported, so it must not be flagged.
    """
    norm = relative_path.replace("\\", "/")
    stem = Path(norm).stem
    stem_lower = stem.lower()

    if stem in _MODULE_ENTRY_POINT_STEMS or stem_lower in _MODULE_ENTRY_POINT_STEMS:
        return True
    # Framework-generated files (next-env.d.ts, _buildManifest.js, cordova.js, ...)
    # Match against the stem prefix, since Path("next-env.d.ts").stem == "next-env.d".
    if any(stem_lower.startswith(g) for g in _GENERATED_STEMS):
        return True
    # Non-source paths: scaffold templates, mobile build output
    if any(part in norm for part in _NON_SOURCE_PATH_PARTS):
        return True
    # Python test files
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    # JS/TS test files
    if ".test." in norm or ".spec." in norm:
        return True
    # __init__.py — always imported implicitly by package machinery
    if "__init__" in norm:
        return True
    # Standalone scripts invoked by a CLI (analyze-*.js, global-setup.ts)
    if stem_lower.startswith("analyze-") or stem_lower in ("global-setup", "global-teardown"):
        return True
    # Template files (backend-test.template.py etc.)
    if ".template." in norm:
        return True
    # Dynamically loaded by frameworks
    for seg in _DYNAMIC_PATH_SEGMENTS:
        if seg in norm:
            return True
    # Bundler output: content-hashed chunk filenames are never source modules.
    # Matches webpack/Metro/Vite patterns like "5333.e1ed8bd7bd6b4bbb.js",
    # "layout-cde9c4d7a42012df.js", "ad2866b8.6c51983a1eb56136.js".
    if _CONTENT_HASH_RE.search(stem):
        return True
    # Runnable Python scripts: a top-level ``if __name__ == "__main__":`` guard
    # means the file is executed directly (``python foo.py`` / ``python -m``),
    # not imported. Such files are entry points regardless of their filename.
    if content is not None and norm.endswith(".py") and '__name__' in content:
        if re.search(r'^if\s+__name__\s*==\s*["\']__main__["\']\s*:', content, re.MULTILINE):
            return True
    return False


def _file_match_keys(relative_path: str) -> list[str]:
    """
    Return all dotted-path suffixes by which this file could be imported.
    E.g. 'backend/myapp/utils/helpers.py' →
         ['backend.myapp.utils.helpers', 'myapp.utils.helpers', 'utils.helpers', 'helpers']
    """
    norm = relative_path.replace("\\", "/").removesuffix(".py")
    # Also handle JS/TS index files and extensions
    for ext in (".ts", ".tsx", ".js", ".jsx"):
        norm = norm.removesuffix(ext)
    # Strip trailing /index so 'components/Button/index' → 'Button'
    if norm.endswith("/index"):
        norm = norm[: -len("/index")]
    parts = norm.split("/")
    return [".".join(parts[i:]) for i in range(len(parts))]


class DeadCodeDetector(BaseDetector):
    category = DetectionCategory.DEAD_CODE
    CONFIDENCE_THRESHOLD = 0.6

    def detect(self, context: AnalysisContext) -> list[Finding]:
        findings: list[Finding] = []

        # --- Pass 2 first: unused modules ---
        # Run module detection before symbol detection so we can collect which
        # files are entirely dead. If a whole module is flagged, emitting every
        # function inside it as a separate finding is redundant double-counting —
        # one issue (the dead file) produces N+1 noise findings.
        module_findings = self._detect_unused_modules(context)
        unused_module_paths: set[str] = {
            ev.file_path
            for f in module_findings
            for ev in f.evidence
        }

        # --- Pass 1: symbol-level dead code ---
        unreferenced = context.symbol_graph.get_unreferenced()
        for sym in unreferenced:
            # Skip symbols inside files already flagged as entirely unused —
            # the module-level finding covers the whole file; per-symbol
            # findings within the same dead file are noise, not signal.
            if sym.file_path in unused_module_paths:
                continue
            # Skip symbols in non-source path trees. _is_module_entry_point
            # returns True for these files (so they never appear in module
            # findings and thus never enter unused_module_paths), but their
            # individual symbols must also be suppressed here.
            sym_norm = sym.file_path.replace("\\", "/")
            if any(part in sym_norm for part in _NON_SOURCE_PATH_PARTS):
                continue
            if _is_entry_point(sym):
                continue
            confidence = _confidence(sym)
            if confidence < self.CONFIDENCE_THRESHOLD:
                continue
            snippet = self._get_snippet(sym, context)
            findings.append(Finding(
                category=DetectionCategory.DEAD_CODE,
                title=f"Unused {sym.kind}: `{sym.name}`",
                description=(
                    f"`{sym.name}` is defined at line {sym.line_start} in `{sym.file_path}` "
                    f"but is never called or imported anywhere in this repository."
                ),
                evidence=[Evidence(
                    file_path=sym.file_path,
                    line_start=sym.line_start,
                    line_end=sym.line_end,
                    snippet=snippet,
                )],
                confidence=confidence,
                risk=_risk(sym),
                effort=EffortLevel.MINUTES,
                benefit="Reduces codebase size and cognitive load. Safe to delete.",
            ))

        findings.extend(module_findings)
        findings.sort(key=lambda f: f.confidence, reverse=True)
        return findings

    def _detect_unused_modules(self, context: AnalysisContext) -> list[Finding]:
        referenced = _build_referenced_module_keys(context)
        # Also gather module references from non-source files (shell scripts,
        # Dockerfiles, CI configs, JSON) so modules invoked via `python -m`
        # or referenced in deployment tooling are not falsely flagged.
        referenced |= _scan_non_source_module_refs(Path(context.repo_path))
        findings: list[Finding] = []

        for file_info in context.files:
            if _is_module_entry_point(file_info.relative_path, file_info.content):
                continue

            match_keys = _file_match_keys(file_info.relative_path)
            if any(k in referenced for k in match_keys):
                continue

            # File has no import anywhere in the repo pointing to it.
            # Confidence: 0.72 — reasonably high but not max, since dynamic
            # loading (importlib, plugin systems) can't be statically detected.
            findings.append(Finding(
                category=DetectionCategory.DEAD_CODE,
                title=f"Unused module: `{Path(file_info.relative_path).name}`",
                description=(
                    f"`{file_info.relative_path}` is never imported by any other file in this "
                    f"repository. The entire module may be dead code."
                ),
                evidence=[Evidence(
                    file_path=file_info.relative_path,
                    line_start=1,
                    line_end=1,
                    snippet=file_info.content.splitlines()[0] if file_info.content else "",
                )],
                confidence=0.72,
                risk=RiskLevel.MEDIUM,
                effort=EffortLevel.MINUTES,
                benefit="Removing an unimported module eliminates its entire maintenance surface.",
            ))

        return findings

    def _get_snippet(self, sym: SymbolDef, context: AnalysisContext) -> str:
        for file_info in context.files:
            if file_info.relative_path == sym.file_path:
                lines = file_info.content.splitlines()
                start = max(0, sym.line_start - 1)
                end = min(len(lines), sym.line_start + 2)  # show definition line + 2
                return "\n".join(lines[start:end])
        return ""
