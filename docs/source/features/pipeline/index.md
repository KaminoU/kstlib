# Pipeline

Declarative, config-driven pipeline execution for sequential workflows.

## What it does

| Capability | Description |
|------------|-------------|
| **Shell commands** | Execute shell commands with env, timeout, working_dir |
| **Python modules** | Run `python -m module` in isolated subprocess |
| **Callable functions** | Import and call Python functions directly |
| **Conditional steps** | Skip or run steps based on previous results |
| **Error policies** | `fail_fast` aborts, `continue` runs all steps |
| **Dry-run mode** | Simulate execution without side effects |
| **Config-driven** | Define pipelines in `kstlib.conf.yml` |

## TL;DR

```python
from kstlib.pipeline import PipelineRunner, PipelineConfig, StepConfig, StepType

config = PipelineConfig(
    name="deploy",
    steps=(
        StepConfig(name="build", type=StepType.SHELL, command="make build"),
        StepConfig(name="test", type=StepType.SHELL, command="make test"),
        StepConfig(name="deploy", type=StepType.SHELL, command="make deploy"),
    ),
)
runner = PipelineRunner(config)
result = runner.run()
print(f"Success: {result.success}, Duration: {result.duration:.1f}s")
```

## Key features

- **Sequential execution** with condition-based step selection
- **Three step types**: shell, python, callable
- **Timeout cascade**: step timeout > pipeline default_timeout
- **Error policies**: fail_fast (with on_failure cleanup) or continue
- **Input validation**: step names, commands, env vars, callable targets
- **Security**: reuses `kstlib.ops` dangerous pattern detection

## Quick start

### Basic shell pipeline

```python
from kstlib.pipeline import PipelineRunner, PipelineConfig, StepConfig, StepType

config = PipelineConfig(
    name="morning-check",
    steps=(
        StepConfig(name="disk", type=StepType.SHELL, command="df -h"),
        StepConfig(name="uptime", type=StepType.SHELL, command="uptime"),
    ),
)
result = PipelineRunner(config).run()
for step in result.results:
    print(f"  {step.name}: {step.status.value}")
```

### Config-driven pipeline

Define in `kstlib.conf.yml`:

```yaml
pipeline:
  default_timeout: 300
  on_error: fail_fast
  pipelines:
    morning-monitoring:
      steps:
        - name: check_services
          type: shell
          command: systemctl status nginx
          timeout: 30
        - name: process_logs
          type: python
          module: my.log_processor
          args: ["--date", "today"]
        - name: send_report
          type: callable
          callable: my.alerts:send_summary
          when: always
```

Load and run:

```python
from kstlib.pipeline import PipelineRunner

runner = PipelineRunner.from_config("morning-monitoring")
result = runner.run()
```

## Shell commands

Shell steps support multi-line commands via YAML block scalars:

```yaml
# Folded scalar (>-) - newlines become spaces
- name: ansible-check
  type: shell
  command: >-
    ansible-playbook --become-method=su
    -i inventory.ini
    ./playbooks/viya-services-status.yml
    > _check.mmsu

# Literal scalar (|) - newlines preserved
- name: multi-host-check
  type: shell
  command: |
    for host in server1 server2; do
      ssh $host "systemctl status viya" >> status.log
    done
```

Environment variables and working directory:

```python
StepConfig(
    name="build",
    type=StepType.SHELL,
    command="make build",
    env={"BUILD_ENV": "production"},
    working_dir="/opt/app",
    timeout=120,
)
```

## Conditional steps

Use the `when` parameter to control step execution:

```python
from kstlib.pipeline import StepCondition

StepConfig(
    name="notify-success",
    type=StepType.CALLABLE,
    callable="my.alerts:send_ok",
    when=StepCondition.ON_SUCCESS,  # Only if all previous steps passed
)

StepConfig(
    name="cleanup",
    type=StepType.SHELL,
    command="rm -f /tmp/*.tmp",
    when=StepCondition.ON_FAILURE,  # Only if a previous step failed
)

StepConfig(
    name="always-log",
    type=StepType.SHELL,
    command="echo done >> pipeline.log",
    when=StepCondition.ALWAYS,  # Run regardless (default)
)
```

## Error handling

### fail_fast (default)

Aborts on first failure. Steps with `when: on_failure` after the failed step still execute for cleanup.

```python
from kstlib.pipeline import ErrorPolicy, PipelineAbortedError

config = PipelineConfig(
    name="deploy",
    steps=(...),
    on_error=ErrorPolicy.FAIL_FAST,
)

try:
    result = PipelineRunner(config).run()
except PipelineAbortedError as e:
    print(f"Aborted at step '{e.step_name}': {e.reason}")
```

### continue

Runs all steps regardless of failures:

```python
config = PipelineConfig(
    name="checks",
    steps=(...),
    on_error=ErrorPolicy.CONTINUE,
)
result = PipelineRunner(config).run()
if not result.success:
    for step in result.failed_steps:
        print(f"  FAILED: {step.name} - {step.error}")
```

## Dry-run mode

Simulate execution without side effects:

```python
result = runner.run(dry_run=True)
for step in result.results:
    print(f"  {step.name}: {step.stdout}")
    # Output: [dry-run] would execute: echo hello
```

## Troubleshooting

### Pipeline not found in config

Ensure the pipeline is defined under `pipeline.pipelines` in `kstlib.conf.yml`:

```yaml
pipeline:
  pipelines:
    my-pipeline:  # <-- This key is used with from_config("my-pipeline")
      steps: [...]
```

### Step timeout

Steps inherit the pipeline `default_timeout` unless they define their own. Set per-step timeouts for long-running commands:

```yaml
- name: long-task
  type: shell
  command: ./long_script.sh
  timeout: 600  # 10 minutes (overrides pipeline default)
```

### Dangerous command patterns

The security validator blocks known dangerous patterns (command substitution, pipe to shell, etc.). If a legitimate command triggers this, consider using a Python step or callable instead.

## See also

- [API Reference](../../api/pipeline.md)
- [Exception Catalog](../../api/exceptions/pipeline.md)
