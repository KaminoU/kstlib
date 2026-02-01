# Claude Code Instructions - kstlib

## Language Rules

- **Chat**: French (conversations, explanations, summaries)
- **Code**: English only (variables, functions, classes, docstrings, comments, commits, Sphinx, warnings)
- **Never** use em dash (U+2014) in docstrings or Markdown - rephrase or use other punctuation

## Commandes Semantiques (Claude DOIT comprendre)

Quand l'utilisateur dit ces mots, appliquer le skill correspondant:

### Commandes de base

| L'utilisateur dit... | Claude execute |
|---------------------|----------------|
| "commit", "commit stp", "commite" | `/commit` - Skill commit securise |
| "todo", "todos", "met a jour la todo" | `/todos` - Skill gestion todos |
| "odj", "ordre du jour", "hello", "salut", "yo" | `/odj` - Briefing de session |
| "check pull", "sync?", "a jour?" | `/check-pull` - Verification sync remote |
| "audit doc sphinx", "audit sphinx", "couverture sphinx", "audit qualite doc sphinx" | `/audit-sphinx-coverage` - Couverture Sphinx vs modules |

### Commandes d'audit (REGLE IMMUABLE)

| L'utilisateur dit... | Claude execute |
|---------------------|----------------|
| "audit", "audit qualite", "lance les audits" | Tous les `/audit-*` en batch (voir workflow ci-dessous) |

#### Workflow Audit Qualite (OBLIGATOIRE)

> **IMPORTANT**: Les audits sont lances en BATCHS pour eviter l'explosion de contexte!

**Phase 1 - Batch MECANIQUE (6 agents en parallele):**
```
audit-imports, audit-dead-code, audit-coverage, audit-md, audit-docstring, audit-sphinx-coverage
```
- `model: sonnet`, `max_turns: 15`, `run_in_background: true`
- Parse de sortie bash/outils, pas de jugement requis

**Phase 2 - Batch JUGEMENT (5 agents en parallele):**
```
audit-dry, audit-typing, audit-complexity, audit-pythonic, audit-performance
```
- `model: sonnet`, `max_turns: 20`, `run_in_background: true`
- Attendre que le Batch 1 soit termine avant de lancer

**Phase 3 - Batch SECURITE (2 agents en parallele):**
```
audit-security, audit-api
```
- `model: opus`, `max_turns: 25`, `run_in_background: true`
- **ZERO COMPROMIS** sur la securite - on utilise le meilleur modele
- Attendre que le Batch 2 soit termine avant de lancer

**Regles pour CHAQUE agent:**
- Ecrire le rapport dans `.claude/skills/<audit-name>/logs/audit-YYYY-MM-DD-HHMMSS.md`
- Gerer la retention (max 7 historiques)
- Retourner UN message minimal: "Rapport ecrit dans <path>" (PAS le contenu!)
- Si contexte limite atteint -> ecrire ce qui a ete trouve et terminer
- **GARDE-FOUS ANTI-EXPLOSION** (voir `.claude/skills/_base/RULES.md`):
  - Lecture fichier: max 500 lignes (utiliser offset/limit)
  - Grep: max 50 matches (utiliser head_limit)
  - Code par finding: max 10 lignes (tronquer)
  - Findings par categorie: max 10 (grouper les similaires)

**Phase 4 - Synthese (Claude principal):**
1. Lire TOUS les rapports dans chaque `logs/`
2. Produire une synthese globale avec:
   - Conventions emoji (🔴 CRITICAL, 🟡 HIGH, 🟢 MEDIUM, ⚪ LOW)
   - Tableau resume des scores par audit
   - **Todo list triee par criticite** (🔴 en premier -> ⚪ en dernier)
3. Proposer les actions correctives

> **Reference**: `.claude/skills/_base/RULES.md` et `REPORT.md`

### Meta-commandes

| L'utilisateur dit... | Claude execute |
|---------------------|----------------|
| "commandes", "liste commandes", "skills", "aide" | Afficher le catalogue des commandes ci-dessous |

> **IMPORTANT**: Ces mots-cles declenchent les skills automatiquement.
> Ne pas demander confirmation, executer directement le skill.

---

## Catalogue des Commandes

### Session & Workflow

| Commande | Description |
|----------|-------------|
| `/odj` | Ordre du jour - Briefing de session |
| `/commit` | Commit securise avec verification branche |
| `/check-pull` | Verification branche et sync remote |
| `/todos` | Gestion des todos (active/done/backlog) |

### Audits Qualite

| Commande | Description |
|----------|-------------|
| `/audit-api` | Contrats API, PEP 561, __all__, stabilite |
| `/audit-complexity` | Fonctions trop complexes (C901) |
| `/audit-coverage` | Couverture des tests unitaires |
| `/audit-dead-code` | Imports inutilises, code mort |
| `/audit-docstring` | Qualite docstrings (anglais, coherence) |
| `/audit-dry` | Code duplique (DRY) |
| `/audit-imports` | Imports circulaires, star imports |
| `/audit-md` | Fichiers Markdown pour Sphinx |
| `/audit-performance` | O(n2), anti-patterns performance |
| `/audit-pythonic` | Style Python idiomatique |
| `/audit-security` | Vulnerabilites, secrets hardcodes |
| `/audit-sphinx-coverage` | Couverture Sphinx vs modules Python, doctests |
| `/audit-typing` | Problemes de typage, Any explicites |

### Execution & Tests

| Commande | Description |
|----------|-------------|
| `tox -e py310` | Tests Python 3.10 (env recommande) |
| `tox -e lint` | Ruff + mypy |
| `tox -e cli` | Tests CLI only |
| `tox -e pylint` | Analyse structurelle profonde |

---

## Visual Conventions (Emoji)

Convention standardisee pour ameliorer la lisibilite des outputs Claude.

### Priorites / Severite

| Emoji | Signification | Usage |
|-------|---------------|-------|
| 🔴 | CRITICAL/URGENT | Action immediate requise |
| 🟡 | HIGH/IMPORTANT | A traiter rapidement |
| 🟢 | MEDIUM/INFO | Information, tout va bien |
| ⚪ | LOW/NEUTRE | Tache normale, sans priorite |

### Status

| Emoji | Signification |
|-------|---------------|
| ✅ | Complete/Valide |
| ❌ | Erreur/Echec |
| ⏳ | En attente |
| 🚧 | En cours |

### Alertes

| Emoji | Signification |
|-------|---------------|
| 🚨 | ALERTE CRITIQUE |
| ⚠️ | Warning |
| 💡 | Suggestion/Tip |
| 📌 | Note importante |

---

## Project Overview

**kstlib** = Config-driven helpers library for Python projects (trading automation stack)

**Principle**: `kwargs > user config (kstlib.conf.yml) > presets > defaults`

**Stack**:
- Python 3.10+ (multi-version CI: 3.10-3.14)
- Testing: pytest + pytest-cov + pytest-asyncio + tox
- Linting: Ruff (linter + formatter) + mypy --strict
- Documentation: Sphinx + Furo theme

## Development Commands

> **REGLE ABSOLUE**: Claude ne doit **JAMAIS** lancer `tox` complet (multi-env).
> Toujours utiliser un environnement specifique: `tox -e py310`, `tox -e lint`, etc.
> Raisons: couteux en ressources, risque d'erreurs en cascade si un env echoue.

> **PowerShell**: Ne pas utiliser `2>null` (cree un fichier "null"). Utiliser `2>$null` a la place.

```bash
# Quality checks (TOUJOURS utiliser -e <env>)
tox -e py310           # Tests Python 3.10 (env par defaut recommande)
tox -e py311           # Tests Python 3.11
tox -e lint            # Ruff + mypy
tox -e cli             # Tests CLI only
tox -e pylint          # Deep structural analysis

# Individual tools
python -m ruff check src/ tests/
python -m ruff format --check src/ tests/
python -m mypy --strict src/

# Cleanup
make tox-clean         # Cross-platform cache cleanup + tox -r
```

## Code Standards

### Type Hints (mandatory)

```python
# Modern Python 3.10+ syntax
def process(data: str | None, items: list[dict[str, Any]]) -> bool:
    ...
```

### Docstrings (Google style, English only)

```python
def load_config(path: str, strict: bool = False) -> Box:
    """Load configuration from a file.

    Args:
        path: Path to the configuration file.
        strict: Whether to enforce strict format checking.

    Returns:
        Box object with configuration data.

    Raises:
        ConfigError: If configuration is invalid.

    Examples:
        >>> from kstlib.config import load_config
        >>> config = load_config("app.yml")
    """
```

### Error Handling

- Use specific exceptions, not bare `except:`
- 4xx errors: `log.warning`
- 5xx errors: `log.error`
- Network errors: `log.exception`

### Tests

> **REGLE ABSOLUE - ZERO COMPROMIS SUR LA COUVERTURE**
>
> Chaque module doit avoir une couverture de tests >= 95%. Aucune exception.
> - Ne JAMAIS proposer d'exclure un module de la couverture pour "ameliorer" le %
> - Ne JAMAIS utiliser `# pragma: no cover` pour cacher du code non teste
> - Le CLI est teste separement (`tox -e cli`) mais doit aussi atteindre 95%
> - Si un module est en cours de dev, tester ce qui est implemente

- Coverage minimum: 95% **per module** (not just global)
- Every test function needs a brief Google-style docstring
- Marker `@pytest.mark.cli` for CLI-specific tests
- No blank lines after docstrings
- Run `tox -e py310` + `tox -e cli` to verify full coverage

## Commit Messages

**Format**: `[#.#.# ::: FLAG1, FLAG2]` + structured body

```text
[1.35.0 ::: AUTH, TESTS]

Add OAuth callback port detection fix

Refactor:
  - CallbackServer now detects actual port when port=0

Tests:
  - Add test_port_zero_assigns_real_port
  - Coverage: 99%
```

**Version Rules (Semver)**:
- **Major (X)**: Breaking changes
- **Minor (Y)**: New features (backward compatible)
- **Patch (Z)**: Bugfixes only

**Soft Tags**: AUTH, CLI, CONFIG, LOGGING, SOPS, MAIL, TESTS, DOCS, REFACTOR, FIX, PERF, BUILD, CHORE

**IMPORTANT - `__version__` in `meta.py`**:
- **NEVER** modify `__version__` on DEV branch (always stays `1.0.0`)
- Version in commit message only (e.g., `[1.37.0 ::: FEAT]`) for tracking
- Only update `__version__` when current branch is `main`

**INTERDIT - Pas de "Co-Authored-By" dans les commits**:
- **JAMAIS** ajouter `Co-Authored-By: Claude ...` ou toute mention similaire
- L'utilisateur paye pour ce service, pas de publicite deguisee pour Anthropic
- Les commits appartiennent a l'utilisateur, pas a Claude

## Git Workflow & Branching Strategy

```
DEV ──(squash)──► RC ──(validate CI/CD)──► main ──► tag v1.x.x
                  │                          │
                  └── delete after ◄─────────┘
```

### Branches

| Branche | Role | Remote | `__version__` |
|---------|------|--------|---------------|
| `DEV` | Developpement quotidien | **LOCAL ONLY** | `1.0.0` (fixe) |
| `RC` | Release Candidate - validation CI/CD | GitHub | `1.0.0` (fixe) |
| `main` | Production, releases officielles | GitHub | Version reelle (e.g., `1.53.0`) |

### Workflow Release

1. **Developper sur DEV**
   - Commits atomiques avec version dans message `[1.53.0 ::: FEAT]`
   - `__version__` reste `1.0.0`

2. **Squash merge vers RC**
   - `git checkout RC && git merge --squash DEV`
   - Push RC sur GitHub pour valider CI/CD

3. **Valider CI/CD sur RC**
   - GitHub Actions: lint, test, build wheel
   - Pas de publish (RC = staging)

4. **Squash merge vers main**
   - `git checkout main && git merge --squash RC`
   - Modifier `__version__` dans `meta.py` → version reelle
   - Push main

5. **Creer tag et publier**
   - `git tag v1.53.0 && git push origin v1.53.0`
   - GitHub Actions: lint, test, build, **publish PyPI**

6. **Cleanup RC**
   - `git branch -d RC && git push origin --delete RC`

### CI/CD par branche

| Branche | Actions declenchees |
|---------|---------------------|
| `DEV` | *(local only - pas de CI)* |
| `RC` | lint, typecheck, test, build (validation) |
| `main` | lint, typecheck, test, build |
| `tag v*` | lint, typecheck, test, build, version-check, **publish PyPI** |

## Project Structure

```
src/kstlib/           # Main package
tests/                # Unit tests
examples/             # Executable examples
docs/source/          # Sphinx documentation
.claude/
  skills/             # Audit skills (audit-dry, audit-security, etc.)
  todos/              # Task tracking (active.md, done.md, backlog.md)
infra/                # Docker (Keycloak, LocalStack)
```

## RAPI Conventions (SAS Viya)

Convention for `.rapi.yml` files in `examples/rapi/viyapi/`.

### Folder Structure

```
viyapi/
  kstlib.conf.yml              # Defaults: base_url, credentials, auth, headers
  <api>/                       # One folder per API family (e.g., annotations)
    root.rapi.yml              # Entry point: name=<api>, includes sub-modules
    <section>.rapi.yml         # One file per OpenAPI section
```

### Endpoint Naming Convention

```
<api>.<endpoint>              # Main section (same name as API)
<api>.<section>-<endpoint>    # Other sections (prefixed)
```

**Example for Annotations API** (3 sections: Root, Annotations, Members):

| Section | Endpoint Name | Full Reference |
|---------|---------------|----------------|
| Root | `root` | `annotations.root` |
| Root | `root-check` | `annotations.root-check` |
| Annotations | `list` | `annotations.list` |
| Annotations | `create` | `annotations.create` |
| Members | `members-list` | `annotations.members-list` |
| Members | `members-create` | `annotations.members-create` |

### File Content Rules

| File | `name` field | `base_url` | `safeguard` |
|------|--------------|------------|-------------|
| `root.rapi.yml` | `<api>` (e.g., `annotations`) | inherited | - |
| `<section>.rapi.yml` | `<api>-<section>` (e.g., `annotations-members`) | **omit** (inherited) | - |
| `kstlib.conf.yml` | - | defined in `defaults` | `required_methods: [DELETE]` |

- **Safeguard**: Only DELETE in global config, never inline on PUT

### Body Templates Convention

**Structure types:**
```yaml
# Simple object
body:
  name*: null        # required field (suffixed with *)
  description: null  # optional field

# Array/batch (ONE example item)
body:
  items:
    - name*: null
      description: null

# Selection/resources
body:
  resources:
    - uri*: null

# No JSON body (text/plain, etc)
body: null
```

**Rules:**
- **Required fields**: Suffix key with `*` (e.g., `name*: null`)
- **Optional fields**: No suffix (e.g., `description: null`)
- **Arrays**: Show ONE example item with all fields
- **Incomplete schemas**: Add `# TODO: schema to complete` for POST/PUT without documented body

## Workflow

### REGLE CRITIQUE - Nouvelle Session

> **OBLIGATOIRE**: Cette regle ne doit JAMAIS etre ignoree !

**Detection nouvelle session**: Message court de salutation (bonjour, coucou, hello, salut, yo, hey, hi) OU question de reprise (on en etait ou?, quoi de neuf?, status?).

**Action IMMEDIATE**: Executer `/odj` pour presenter un "Ordre du jour":

```
## Ordre du jour - Session kstlib

### 🔄 Synchronisation Git
[Branche actuelle, ahead/behind origin]

### 🚧 Taches en cours (.claude/todos/active.md)
- [ ] Tache prioritaire 1
- [ ] Tache prioritaire 2

### 📋 Derniers commits
| Hash | Message |
|------|---------|
| abc1234 | [1.37.0] Description... |

### 🟢 Actions recommandees
🔴 **URGENT**: [Action bloquante immediate]
🟡 **Important**: [Action suivante]
⚪ [Tache normale]
```

**Fichiers a lire**:
1. `.claude/todos/active.md` - Taches en cours (PRIORITAIRE)
2. `git log --oneline -5` - Derniers commits
3. `git status` - Etat du repo

---

### Session Start (apres l'ordre du jour)
1. Check `.claude/todos/active.md` for current tasks
2. Review recent commits: `git log --oneline -10`

### During Session
- Use TodoWrite tool for task tracking
- Atomic commits per feature/fix
- Run `tox -e py310` + `tox -e lint` before committing (JAMAIS `tox` complet)

### Session End
1. Update `.claude/todos/done.md` with completed items
2. Move new ideas to `.claude/todos/backlog.md`

## Infrastructure

### Keycloak (OAuth2/OIDC testing)
- URL: http://localhost:8080/admin
- Admin: `admin` / `admin`
- Realm: `kstlib-test`
- Test user: `testuser` / `testpass123`

### LocalStack (AWS KMS testing)
- URL: http://localhost:4566

## Key Files

| Purpose | File |
|---------|------|
| Version | `src/kstlib/meta.py` |
| Dependencies | `pyproject.toml` |
| Default config | `src/kstlib/kstlib.conf.yml` |
| Ruff/mypy config | `pyproject.toml` |
| Pre-commit | `.github/hooks/pre_commit_check.py` |

## Anti-Patterns to Avoid

- No French in code, docstrings, or Sphinx docs
- No `# type: ignore` without justification
- No access to protected members (`_var`) in tests - use public API
- No `== True/False/None` - use `is True/False/None`
- No mutable default arguments (`def foo(items=[]): ...`)
- No bare `except:` - always specify exception type
- **NEVER run `tox` without `-e`** - always specify environment (`tox -e py310`, `tox -e lint`)
