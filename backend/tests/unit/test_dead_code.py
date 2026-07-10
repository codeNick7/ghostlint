"""Tests for the DeadCodeDetector."""
from __future__ import annotations
import pytest
from tiramasu_engine.detectors.dead_code.detector import DeadCodeDetector
from tiramasu_engine.graph.symbol_graph import SymbolGraph
from tiramasu_engine.graph.context import AnalysisContext
from tiramasu_engine.models.findings import DetectionCategory
from tests.unit.conftest import make_symbol_def, make_symbol_ref, make_file_info


def make_context(defs=None, refs=None, files=None):
    g = SymbolGraph()
    for d in (defs or []):
        g.add_definition(d)
    for r in (refs or []):
        g.add_reference(r)
    return AnalysisContext(
        files=files or [],
        symbol_graph=g,
        repo_path=".",
    )


def test_detects_unreferenced_function() -> None:
    d = make_symbol_def("orphan", kind="function", file_path="utils.py", is_private=True)
    ctx = make_context(defs=[d])
    findings = DeadCodeDetector().detect(ctx)
    assert any(f.category == DetectionCategory.DEAD_CODE for f in findings)


def test_does_not_flag_referenced_function() -> None:
    d = make_symbol_def("used_func", kind="function", file_path="utils.py")
    r = make_symbol_ref("used_func", file_path="main.py")
    ctx = make_context(defs=[d], refs=[r])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("used_func" in f.title for f in findings)


def test_does_not_flag_entry_points() -> None:
    """main(), test_ prefixed functions, and dunder methods are entry points."""
    entry_defs = [
        make_symbol_def("main", kind="function", file_path="app.py"),
        make_symbol_def("test_something", kind="function", file_path="test_app.py"),
        make_symbol_def("__init__", kind="method", file_path="cls.py"),
    ]
    ctx = make_context(defs=entry_defs)
    findings = DeadCodeDetector().detect(ctx)
    flagged = {f.title for f in findings}
    assert not any("main" in t or "test_something" in t or "__init__" in t for t in flagged)


def test_does_not_flag_decorated_routes() -> None:
    d = make_symbol_def(
        "get_health",
        kind="function",
        file_path="routes.py",
        decorators=["@router.get('/health')"],
    )
    ctx = make_context(defs=[d])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("get_health" in f.title for f in findings)


def test_confidence_higher_for_private() -> None:
    d_private = make_symbol_def("_unused_helper", kind="function", file_path="utils.py", is_private=True)
    d_public = make_symbol_def("unused_helper", kind="function", file_path="utils.py", is_private=False)
    ctx = make_context(defs=[d_private, d_public])
    findings = DeadCodeDetector().detect(ctx)
    private_f = next((f for f in findings if "_unused_helper" in f.title), None)
    public_f = next((f for f in findings if "unused_helper" in f.title and "_" not in f.title.split("`")[1][:1]), None)
    if private_f and public_f:
        assert private_f.confidence >= public_f.confidence


def test_does_not_flag_alembic_upgrade_downgrade() -> None:
    """upgrade/downgrade in alembic migration files are called by Alembic at runtime."""
    defs = [
        make_symbol_def("upgrade", kind="function", file_path="backend/alembic/versions/20251108_add_users.py"),
        make_symbol_def("downgrade", kind="function", file_path="backend/alembic/versions/20251108_add_users.py"),
        make_symbol_def("upgrade", kind="function", file_path="migrations/versions/0001_init.py"),
    ]
    ctx = make_context(defs=defs)
    findings = DeadCodeDetector().detect(ctx)
    flagged_titles = {f.title for f in findings}
    assert not any("upgrade" in t or "downgrade" in t for t in flagged_titles), (
        f"Alembic migration entry points should not be flagged: {flagged_titles}"
    )


def test_does_not_flag_django_model() -> None:
    """Classes inheriting from framework base classes must not be flagged."""
    framework_cases = [
        ("Article", "class", "models.py", ["Model"]),
        ("ArticleListView", "class", "views.py", ["ListView"]),
        ("ArticleSerializer", "class", "serializers.py", ["ModelSerializer"]),
        ("UserSchema", "class", "schemas.py", ["BaseModel"]),
        ("ArticleAdmin", "class", "admin.py", ["ModelAdmin"]),
        ("UserTask", "class", "tasks.py", ["Task"]),
    ]
    for name, kind, fp, bases in framework_cases:
        sym = make_symbol_def(name, kind=kind, file_path=fp)
        sym = type(sym)(  # rebuild with base_classes field
            **{**sym.__dict__, "base_classes": bases}
        )
        ctx = make_context(defs=[sym])
        findings = DeadCodeDetector().detect(ctx)
        flagged = [f.title for f in findings if name in f.title and "module" not in f.title]
        assert not flagged, f"{name}({bases}) should not be flagged, got: {flagged}"


def test_does_not_flag_celery_shared_task() -> None:
    """@shared_task decorated functions are called by Celery worker, not by import."""
    sym = make_symbol_def("send_email", kind="function", file_path="tasks.py",
                          decorators=["@shared_task"])
    ctx = make_context(defs=[sym])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("send_email" in f.title for f in findings)


def test_does_not_flag_django_receiver() -> None:
    """@receiver decorated functions are called by Django's signal dispatcher."""
    sym = make_symbol_def("on_user_save", kind="function", file_path="signals.py",
                          decorators=["@receiver(post_save, sender=User)"])
    ctx = make_context(defs=[sym])
    findings = DeadCodeDetector().detect(ctx)
    assert not any("on_user_save" in f.title for f in findings)


def test_path_alias_imports_resolve_correctly() -> None:
    """@/ and ~/ path alias imports (Next.js, Vite) must clear the referenced module."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    files = [
        # components/ui/ is the shadcn library directory — suppressed entirely
        # as a design-system-as-code install pattern (not dead code).
        make_file_info("components/ui/button.tsx",
                       'export function Button() {}', "typescript"),
        # components/shared/ is a regular shared component tree — unused files here ARE flagged.
        make_file_info("components/shared/ghost.tsx",
                       'export function Ghost() {}', "typescript"),
        make_file_info("lib/utils.ts",
                       'export function cn() {}', "typescript"),
        make_file_info("app/page.tsx",
                       'import { Button } from "@/components/ui/button"\nexport default function Page() {}',
                       "typescript"),
        make_file_info("app/layout.tsx",
                       'import { cn } from "~/lib/utils"\nexport default function Layout() {}',
                       "typescript"),
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=".")
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = [f.evidence[0].file_path for f in findings]
    # components/ui/ is suppressed as a shadcn library pattern — neither file flagged.
    assert "components/ui/button.tsx" not in flagged, "shadcn ui/ dir should be suppressed entirely"
    assert "components/ui/ghost.tsx" not in flagged, "shadcn ui/ dir should be suppressed entirely"
    # Regular shared component that is genuinely unused should be flagged.
    assert "components/shared/ghost.tsx" in flagged, "Genuinely unused component should be flagged"
    assert "lib/utils.ts" not in flagged, "~/ alias import should clear utils.ts"


def test_detects_unused_module_python() -> None:
    """A Python file never imported by any other file is flagged as an unused module."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    files = [
        make_file_info("src/main.py", "from src.utils.helpers import help\n"),
        make_file_info("src/utils/helpers.py", "def help(): pass\n"),
        make_file_info("src/orphan.py", "def noop(): pass\n"),  # never imported
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=".")
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = [f.evidence[0].file_path for f in findings]
    assert "src/orphan.py" in flagged
    assert "src/utils/helpers.py" not in flagged
    assert "src/main.py" not in flagged  # main.py is entry point stem


def test_detects_unused_module_typescript() -> None:
    """A TS component never imported by any other file is flagged."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    files = [
        make_file_info("components/Button.tsx", "export default function Button() {}", "typescript"),
        make_file_info("pages/index.tsx", 'import Button from "../components/Button"\nexport default function Home() {}', "typescript"),
        make_file_info("components/Ghost.tsx", "export default function Ghost() {}", "typescript"),
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=".")
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = [f.evidence[0].file_path for f in findings]
    assert "components/Ghost.tsx" in flagged
    assert "components/Button.tsx" not in flagged
    assert "pages/index.tsx" not in flagged  # index is entry point stem


def test_findings_sorted_by_confidence() -> None:
    defs = [
        make_symbol_def(f"func_{i}", kind="function", file_path="utils.py", is_private=(i % 2 == 0))
        for i in range(5)
    ]
    ctx = make_context(defs=defs)
    findings = DeadCodeDetector().detect(ctx)
    confidences = [f.confidence for f in findings]
    assert confidences == sorted(confidences, reverse=True)


def test_is_module_entry_point_main_script() -> None:
    """A Python file with a top-level `if __name__ == "__main__":` guard is a
    runnable entry point — it must not be flagged as an unused module."""
    from tiramasu_engine.detectors.dead_code.detector import _is_module_entry_point

    runnable = (
        'def seed():\n    pass\n\n'
        'if __name__ == "__main__":\n    seed()\n'
    )
    assert _is_module_entry_point("backend/app/db/init_db.py", content=runnable)
    # Without the guard, the same file is not auto-skipped (still may be flagged).
    assert not _is_module_entry_point(
        "backend/app/db/init_db.py", content="def seed():\n    pass\n"
    )
    # Indented __main__ (inside a function) must NOT count — only top-level guards
    # mean the file is runnable directly.
    nested = (
        'def run():\n    if __name__ == "__main__":\n        pass\n'
    )
    assert not _is_module_entry_point("backend/app/db/init_db.py", content=nested)


def test_is_module_entry_point_claude_hook() -> None:
    """Files under .claude/hooks/ are invoked by config (settings.local.json),
    never imported as modules — they must not be flagged as unused."""
    from tiramasu_engine.detectors.dead_code.detector import _is_module_entry_point

    assert _is_module_entry_point(".claude/hooks/py_syntax_check.py")
    assert _is_module_entry_point(".claude/hooks/ts_prettier_check.py")


def test_unused_module_main_script_not_flagged(tmp_path) -> None:
    """A Python file with `if __name__ == "__main__":` is a runnable script and
    must not be flagged as an unused module, even though nothing imports it."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    runnable_content = (
        'def seed():\n    pass\n\n'
        'if __name__ == "__main__":\n    seed()\n'
    )
    files = [
        make_file_info("app/main.py", "def run(): pass\n"),
        make_file_info("app/db/init_db.py", runnable_content),  # __main__ script
        make_file_info("app/orphan.py", "def dead(): pass\n"),  # genuinely unused
    ]
    # Use tmp_path as repo_path so the non-source scanner finds nothing extra.
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=str(tmp_path))
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = {f.evidence[0].file_path for f in findings}
    assert "app/db/init_db.py" not in flagged, "runnable __main__ script should not be flagged"
    assert "app/orphan.py" in flagged, "genuinely unused module should still be flagged"


def test_unused_module_referenced_in_shell_script_not_flagged(tmp_path) -> None:
    """A module invoked via `python -m app.db.seed_catalog` in a deployment
    shell script must not be flagged as an unused module."""
    from tiramasu_engine.graph.context import AnalysisContext
    from tiramasu_engine.graph.symbol_graph import SymbolGraph
    from tests.unit.conftest import make_file_info

    # Write a real .sh file in the tmp repo that references the module via -m.
    (tmp_path / "deploy.sh").write_text(
        "#!/bin/bash\npython -m app.db.seed_catalog --reset\n"
    )
    files = [
        make_file_info("app/main.py", "def run(): pass\n"),
        # seed_catalog has no __main__ guard and is never imported — but it IS
        # referenced via `python -m` in deploy.sh.
        make_file_info("app/db/seed_catalog.py", "def seed_database(): pass\n"),
        make_file_info("app/orphan.py", "def dead(): pass\n"),  # genuinely unused
    ]
    ctx = AnalysisContext(files=files, symbol_graph=SymbolGraph(), repo_path=str(tmp_path))
    findings = DeadCodeDetector()._detect_unused_modules(ctx)
    flagged = {f.evidence[0].file_path for f in findings}
    assert "app/db/seed_catalog.py" not in flagged, (
        "module referenced via `python -m` in a .sh should not be flagged"
    )
    assert "app/orphan.py" in flagged, "genuinely unused module should still be flagged"

