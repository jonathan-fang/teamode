"""Tests for app/constants.py: import hygiene and exact copy strings."""

from __future__ import annotations

import ast
from pathlib import Path

from app.constants import TEACUP_BANNER

_CONSTANTS_PATH = Path(__file__).resolve().parent.parent / "app" / "constants.py"


def _imported_module_names() -> set[str]:
    """Return every full module path imported by app/constants.py.

    Includes the top-level module name and, for ``from X.Y import Z``, the
    dotted ``X.Y`` module path — so ``from app.config import FOO`` is caught,
    not just a bare ``app``.
    """
    tree = ast.parse(_CONSTANTS_PATH.read_text(), filename=str(_CONSTANTS_PATH))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module is not None:
                names.add(node.module)
                # Also record the import target joined to the module, e.g.
                # "from app import config" -> "app.config".
                for alias in node.names:
                    names.add(f"{node.module}.{alias.name}")
    return names


def test_constants_does_not_import_discord_or_app_config() -> None:
    """app/constants.py must stay free of discord and app.config imports."""
    imported = _imported_module_names()
    assert "discord" not in imported
    assert "app.config" not in imported
    # No import of app.discord_bot either — constants.py must not depend on
    # the Discord-facing wiring layer.
    assert not any(name.startswith("app.discord_bot") for name in imported)


def test_teacup_banner_exact_lines() -> None:
    """TEACUP_BANNER renders as the exact 8-line ASCII teacup, leading spaces intact."""
    lines = TEACUP_BANNER.split("\n")
    assert lines == [
        "     )  )",
        "    (  (",
        "   _______",
        "  |       |__",
        "  | TEA   |  )",
        "  |  MODE |_/",
        "   \\_____/",
        "  '-------'",
    ]
    # Leading-space counts per line, as specified.
    assert [len(line) - len(line.lstrip(" ")) for line in lines] == [
        5,
        4,
        3,
        2,
        2,
        2,
        3,
        2,
    ]
