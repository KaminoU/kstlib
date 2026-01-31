# Development

Thanks for your interest in this personal project! Whether you're here to explore the code,
report an issue, or contribute, it's much appreciated.

This section covers the development workflow, testing strategy, and infrastructure setup
for anyone who wants to hack on kstlib.

```{note}
This project uses strict quality gates: **tox** for multi-version testing, **pre-commit** hooks,
and a CI/CD pipeline that enforces 95%+ coverage per module.
```

---

::::{grid} 3
:gutter: 3

:::{grid-item-card} Contribution Workflow
:link: workflow
:link-type: doc

Git branching, commit conventions, release process.
:::

:::{grid-item-card} Testing
:link: testing
:link-type: doc

pytest, tox multi-env, coverage requirements.
:::

:::{grid-item-card} Quality & CI
:link: quality
:link-type: doc

Ruff, mypy, pre-commit hooks, tox marker system.
:::

:::{grid-item-card} Makefile
:link: makefile
:link-type: doc

Make targets for common dev tasks.
:::

:::{grid-item-card} Performance
:link: performance
:link-type: doc

Benchmarking and optimization guidelines.
:::

:::{grid-item-card} Infrastructure
:link: infra/index
:link-type: doc

Keycloak, LocalStack for local testing.
:::

:::{grid-item-card} Secrets Management
:link: secrets-management
:link-type: doc

SOPS setup, key management, best practices.
:::

:::{grid-item-card} Secrets Workflow
:link: secrets-workflow
:link-type: doc

Day-to-day secrets operations.
:::

:::{grid-item-card} Binary Dependencies
:link: binary-dependencies
:link-type: doc

System dependencies and installation.
:::

::::

```{toctree}
:hidden:
:maxdepth: 1

workflow
testing
quality
makefile
performance
infra/index
secrets-management
secrets-workflow
binary-dependencies
```
