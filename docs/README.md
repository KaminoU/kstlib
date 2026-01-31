# Kstlib Documentation

Documentation for kstlib, built with Sphinx and rendered through MyST Markdown.

**Single Source of Truth**: All dependencies are in `pyproject.toml` ✨
**Source format**: `.md` files interpreted by MyST (reStructuredText directives live inside `{eval-rst}` blocks).

## 🚀 Quick Start

### Install documentation dependencies

```bash
# Install kstlib with documentation dependencies
pip install -e .[docs]
```

### Build documentation

```bash
cd docs
sphinx-build -E -b html source build/html  # -E forces a fresh environment rebuild
```

```bash
# Or using make (Unix/WSL) from inside docs/
cd docs
SPHINXOPTS=-E make html
# Or clean artifacts then rebuild after the first command
make clean && make html
```

### View documentation

Open the generated HTML in your browser:

```bash
# On Linux/Mac
open build/html/index.html

# On Windows
start build/html/index.html

# Or with Python
python -m http.server -d build/html 8000
# Then visit http://localhost:8000
```

## Documentation Structure

```text
docs/
├── source/                   # Documentation source files (MyST Markdown)
│   ├── conf.py              # Sphinx configuration
│   ├── index.md             # Homepage + toctree
│   ├── api/                 # API reference stubs
│   │   ├── cache.md
│   │   ├── config.md
│   │   └── ...
│   ├── guide/               # User guides
│   │   ├── configuration.md
│   │   └── best_practices.md
│   ├── examples/            # Example walkthroughs
│   │   └── config.md
│   ├── implementation/      # Deep dives per subsystem
│   ├── development/         # Contributing notes, release steps
│   ├── changelog.md
│   ├── license.md
│   └── todo.md              # Mirrors .github/todos
├── build/                   # Generated documentation (gitignored)
├── Makefile                 # Build automation
└── README.md                # This file
```

## 📦 Installation Options

All dependencies are managed in `pyproject.toml`:

```bash
# For users (install kstlib only)
pip install kstlib

# For developers (includes testing, linting, typing)
pip install -e .[dev]

# For documentation writers (includes Sphinx and extensions)
pip install -e .[docs]

# For maintainers (includes build and release tools)
pip install -e .[build]

# For CI/CD (multi-version testing)
pip install -e .[tox]

# Everything (all optional dependencies)
pip install -e .[all]
```

## 🚢 Building for ReadTheDocs

The documentation is configured to build automatically on ReadTheDocs using `.readthedocs.yaml`.

ReadTheDocs uses `pyproject.toml` directly - **no separate requirements.txt needed!** ✨

Configuration is in:

- `.readthedocs.yaml` (root of project)
- `docs/source/conf.py` (Sphinx config)
- `pyproject.toml` → `[project.optional-dependencies.docs]` (dependencies)

## Editing Documentation

### Adding New Pages

1. Create a new `.md` file in the appropriate directory (all guides use MyST Markdown)
2. Add it to the `toctree` in `source/index.md` or the relevant parent page using standard MyST syntax

### API Documentation

API documentation is auto-generated from docstrings using Sphinx autodoc. Because we rely on MyST Markdown,
wrap autodoc directives in `{eval-rst}` blocks when editing `.md` files:

````markdown
```{eval-rst}
.. automodule:: kstlib.newmodule
   :members:
   :undoc-members:
   :show-inheritance:
```
````

### Code Examples

Use `literalinclude` inside MyST fences so Sphinx keeps syntax highlighting consistent:

````markdown
```{literalinclude} ../../../examples/myexample.py
:language: python
:linenos:
```
````

## Common Tasks

### Clean Build

```bash
# With Makefile
make clean

# Or manually
rm -rf build/
```

### Check for Broken Links

```bash
python -m sphinx -b linkcheck source build/linkcheck
```

### Build PDF (requires LaTeX)

```bash
# With Makefile
make latexpdf

# Or manually with sphinx-build
python -m sphinx -b latex source build/latex
# Then build PDF from LaTeX
cd build/latex && make
```

## Troubleshooting

### ModuleNotFoundError

If autodoc fails to import modules:

1. Install kstlib in development mode:

   ```bash
   pip install -e ..
   ```

2. Or install all dependencies:

   ```bash
   pip install -e ..[dev]
   ```

### Theme Not Found

Install the ReadTheDocs theme:

```bash
pip install sphinx-rtd-theme
```

### Build Warnings

To see detailed build warnings:

```bash
python -m sphinx -W -b html source build/html
```

The `-W` flag treats warnings as errors, causing the build to fail on any warning.

## Contributing

When adding documentation:

1. Follow the existing structure
2. Use proper RST syntax
3. Add examples where appropriate
4. Test your changes locally before committing
5. Check for warnings: `python -m sphinx -b html source build/html`

## Resources

- [Sphinx Documentation](https://www.sphinx-doc.org/)
- [reStructuredText Primer](https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html)
- [ReadTheDocs Guide](https://docs.readthedocs.io/)
- [Sphinx autodoc](https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html)
