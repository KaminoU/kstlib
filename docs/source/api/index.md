# API Reference

Complete API documentation for all `kstlib` modules. Each page documents public classes, functions, and configuration options with type signatures and usage examples.

---

::::{grid} 3
:gutter: 3

:::{grid-item-card} alerts
:link: alerts
:link-type: doc

`AlertManager`, channels (Slack, Email), throttling.
:::

:::{grid-item-card} auth
:link: auth
:link-type: doc

`OAuth2Client`, `TokenStorage`, PKCE, providers.
:::

:::{grid-item-card} cache
:link: cache
:link-type: doc

`@cached`, `CacheStrategy`, memory/file backends.
:::

:::{grid-item-card} config
:link: config
:link-type: doc

`load_config()`, `ConfigLoader`, presets, includes.
:::

:::{grid-item-card} db
:link: db
:link-type: doc

`AsyncDatabase`, `ConnectionPool`, SQLCipher.
:::

:::{grid-item-card} helpers
:link: helpers
:link-type: doc

`TimeTrigger`, time-based scheduling utilities.
:::

:::{grid-item-card} logging
:link: logging
:link-type: doc

`LogManager`, `setup_logging()`, TRACE level.
:::

:::{grid-item-card} mail
:link: mail
:link-type: doc

`MailBuilder`, transports (SMTP, Gmail, Resend).
:::

:::{grid-item-card} metrics
:link: metrics
:link-type: doc

`@metrics`, `@call_stats`, `Stopwatch`.
:::

:::{grid-item-card} monitoring
:link: monitoring
:link-type: doc

`StatusCell`, `MetricCell`, Jinja2 renderer.
:::

:::{grid-item-card} ops
:link: ops
:link-type: doc

`SessionManager`, `TmuxRunner`, `ContainerRunner`.
:::

:::{grid-item-card} pipeline
:link: pipeline
:link-type: doc

`PipelineRunner`, `StepConfig`, `ShellStep`, `PythonStep`.
:::

:::{grid-item-card} rapi
:link: rapi
:link-type: doc

`RapiClient`, `call()`, HMAC signing, credentials.
:::

:::{grid-item-card} resilience
:link: resilience
:link-type: doc

`CircuitBreaker`, `Heartbeat`, `Watchdog`, `RateLimiter`.
:::

:::{grid-item-card} secrets
:link: secrets
:link-type: doc

`SecretResolver`, SOPS, KMS, keyring providers.
:::

:::{grid-item-card} secure
:link: secure
:link-type: doc

`PathGuardrails`, permissions, path validation.
:::

:::{grid-item-card} ui
:link: ui/index
:link-type: doc

`Panel`, `Table`, `Spinner` for Rich terminal output.
:::

:::{grid-item-card} utils
:link: utils
:link-type: doc

Formatting, validators, `LazyModule`, helpers.
:::

:::{grid-item-card} websocket
:link: websocket
:link-type: doc

`WebSocketManager`, reconnection, proactive control.
:::

::::

---

::::{grid} 1
:gutter: 3

:::{grid-item-card} Exception Catalog
:link: exceptions/index
:link-type: doc

Complete catalog of all exceptions by module with mitigation guides.
:::

::::

---

```{tip}
For narrative guides with practical examples, see {doc}`../features/index`.
```

```{toctree}
:hidden:
:maxdepth: 2

alerts
auth
cache
config
db
helpers
logging
mail
metrics
monitoring
ops
pipeline
rapi
resilience
secrets
secure
ui/index
utils
websocket
exceptions/index
```
