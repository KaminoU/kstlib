"""Project-level Sphinx configuration for the kstlib documentation site."""
# pylint: disable=invalid-name

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import inspect
import sys
from pathlib import Path
from typing import Any

_TYPER_PARAM_TYPES: tuple[type[Any], ...] = ()
try:  # pragma: no cover - Typer optional during doc builds
    from typer.models import ArgumentInfo as _ArgumentInfo
    from typer.models import OptionInfo as _OptionInfo
except Exception:  # pylint: disable=broad-except
    pass
else:
    _TYPER_PARAM_TYPES = (_ArgumentInfo, _OptionInfo)

# -- Path setup --------------------------------------------------------------
# Add the project root to sys.path for autodoc
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from kstlib.meta import (  # noqa: E402  # pylint: disable=wrong-import-position
    __app_name__,
    __author__,
    __version__,
)

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = __app_name__
copyright = f"2025, {__author__}"  # noqa: A001  # Sphinx requires this name
author = __author__
release = __version__
version = __version__

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",  # Auto-generate docs from docstrings
    "sphinx.ext.napoleon",  # Support for Google/NumPy style docstrings
    "sphinx.ext.viewcode",  # Add [source] links to documentation
    "sphinx.ext.intersphinx",  # Link to other project's documentation
    "sphinx.ext.todo",  # Support for todo items
    "sphinx.ext.coverage",  # Check documentation coverage
    "sphinx.ext.autosummary",  # Generate autodoc summaries
    "myst_parser",  # Markdown/MDX-style authoring via MyST
    "sphinx_togglebutton",  # Collapsible sections in reST (dropdown directive)
    "sphinx_design",  # Design components (includes dropdown directive)
]

# MyST configuration mirrors the furo docs setup so we can mix Markdown & rST.
myst_enable_extensions = [
    "colon_fence",
    "deflist",
]
myst_heading_anchors = 3

# Napoleon settings (for Google-style docstrings)
napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = True
napoleon_type_aliases = None
napoleon_attr_annotations = True

# Autodoc settings
autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

# Autosummary settings
autosummary_generate = True

# Templates path
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
exclude_patterns: list[str] = []

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
html_title = __app_name__
html_logo = "../../assets/kstlib.svg"

# Furo theme options - Lokaal color palette
html_theme_options = {
    # GitHub integration - adds "Edit on GitHub" and source links
    "source_repository": "https://github.com/KaminoU/kstlib",
    "source_branch": "main",
    "source_directory": "docs/source/",
    # Footer icons with GitHub link
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/KaminoU/kstlib",
            "html": """
                <svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 16 16">
                    <path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path>
                </svg>
            """,
            "class": "",
        },
    ],
    "light_css_variables": {
        # Brand
        "color-brand-primary": "#4A90E2",
        "color-brand-content": "#4A90E2",
        # Backgrounds
        "color-background-primary": "#ffffff",
        "color-background-secondary": "#f6f8fa",
        "color-background-border": "#d0d7de",
        # Text
        "color-foreground-primary": "#1f2328",
        "color-foreground-secondary": "#656d76",
        "color-foreground-muted": "#8b949e",
        # Admonitions
        "color-admonition-title-background--note": "rgba(74, 144, 226, 0.15)",
        "color-admonition-title-background--tip": "rgba(22, 160, 133, 0.15)",
        "color-admonition-title-background--warning": "rgba(241, 196, 15, 0.15)",
        "color-admonition-title-background--danger": "rgba(232, 90, 79, 0.15)",
        "color-admonition-title--note": "#4A90E2",
        "color-admonition-title--tip": "#16A085",
        "color-admonition-title--warning": "#9a7b00",
        "color-admonition-title--danger": "#E85A4F",
    },
    "dark_css_variables": {
        # Brand
        "color-brand-primary": "#4A90E2",
        "color-brand-content": "#4A90E2",
        # Backgrounds - Lokaal dark theme
        "color-background-primary": "#0D1117",
        "color-background-secondary": "#161B22",
        "color-background-hover": "#21262D",
        "color-background-hover--transparent": "rgba(33, 38, 45, 0.5)",
        "color-background-border": "#30363D",
        # Text - Lokaal
        "color-foreground-primary": "#E6EDF3",
        "color-foreground-secondary": "#8B949E",
        "color-foreground-muted": "#6E7681",
        # Admonitions - Lokaal semantic colors
        "color-admonition-title-background--note": "rgba(167, 139, 250, 0.15)",
        "color-admonition-title-background--tip": "rgba(22, 160, 133, 0.15)",
        "color-admonition-title-background--warning": "rgba(241, 196, 15, 0.15)",
        "color-admonition-title-background--danger": "rgba(232, 90, 79, 0.15)",
        "color-admonition-title--note": "#A78BFA",
        "color-admonition-title--tip": "#16A085",
        "color-admonition-title--warning": "#F1C40F",
        "color-admonition-title--danger": "#E85A4F",
    },
    "sidebar_hide_name": True,
}


def _sanitize_parameter_default(default: Any) -> Any:
    """Return a human-friendly default for Typer parameters when possible."""
    if _TYPER_PARAM_TYPES and isinstance(default, _TYPER_PARAM_TYPES):
        normalized = getattr(default, "default", inspect.Signature.empty)
        if normalized in (inspect.Signature.empty, Ellipsis):
            return inspect.Signature.empty
        return normalized
    return default


def _unwrap_signature_target(obj: Any) -> Any:
    """Best-effort inspect.unwrap() that tolerates non-callables."""
    try:
        return inspect.unwrap(obj)
    except Exception:  # pylint: disable=broad-except
        return obj


def _normalized_signature(obj: Any) -> inspect.Signature | None:
    """Return the callable signature when introspection succeeds."""
    target = _unwrap_signature_target(obj)
    try:
        return inspect.signature(target)
    except (TypeError, ValueError):  # pragma: no cover - non-callables
        return None


def _autodoc_clean_signature(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    app: Any,
    what: str,
    name: str,
    obj: Any,
    options: Any,
    signature: str | None,
    return_annotation: str | None,
) -> tuple[str, Any] | None:
    """Replace noisy signatures for decorated functions before rendering."""
    del app, name, options, signature  # unused autodoc parameters
    if what not in {"function", "method"}:
        return None

    normalized = _normalized_signature(obj)
    if normalized is None:
        return None

    cleaned_parameters = []
    for param in normalized.parameters.values():
        sanitized_default = _sanitize_parameter_default(param.default)
        if sanitized_default is not param.default:
            param = param.replace(default=sanitized_default)
        cleaned_parameters.append(param)

    sanitized_signature = normalized.replace(parameters=cleaned_parameters)
    rendered_signature = str(sanitized_signature)
    rendered_return: str | None
    if sanitized_signature.return_annotation is not inspect.Signature.empty:
        rendered_return = str(sanitized_signature.return_annotation)
    else:
        rendered_return = return_annotation

    return (rendered_signature, rendered_return)


def setup(app: Any) -> None:
    """Register custom assets for the documentation build.

    Args:
        app: Active Sphinx application instance.
    """
    # Ensure the default color scheme starts in dark mode before Furo loads.
    app.add_js_file("set-default-dark-mode.js", priority=150)
    # Lokaal color palette and custom styling
    app.add_css_file("custom.css", priority=150)
    app.connect("autodoc-process-signature", _autodoc_clean_signature)


# -- Options for intersphinx extension ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html#configuration

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

# -- Options for todo extension ----------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/todo.html#configuration

todo_include_todos = True
