# Skills

This directory holds community-contributed starter skills for KidEconomy agents.

## Skill Format

A KidEconomy skill is a self-contained unit of capability that an agent can install and invoke. Each skill lives in its own subdirectory and ships:

```
skills/
  my_skill/
    skill.yaml        # metadata + manifest (required)
    README.md         # human-readable description (required)
    handler.py        # entry point invoked by the sandbox (required)
    requirements.txt  # extra pip deps, pinned (optional)
```

**Directory names must use underscores** (`my_skill`, not `my-skill`). The
skill name in `skill.yaml` may use kebab-case (`my-skill`), but the Python
package directory must be a valid identifier so imports work cleanly:

```python
from skills.my_skill.handler import run
```

### `skill.yaml`

```yaml
name: my-skill
version: 0.1.0
category: productivity
description: One-line summary shown in `kidecon skills browse`.
entrypoint: handler.py
permissions:
  tools:
    - file_read
    - file_append_markdown
  network: false
config:
  example_option:
    default: hello
    description: A user-tunable option.
```

### `handler.py`

```python
import logging

logger = logging.getLogger(__name__)


def run(args: list[str], config: dict) -> dict:
    """Skill entry point. Return a JSON-serializable result dict."""
    logger.info("my-skill run with args=%s", args)
    return {"ok": True}
```

## Conventions

- **Logging first.** Every `.py` file starts with `import logging; logger = logging.getLogger(__name__)`.
- **No secrets in code.** Read keys from keyring via the wrapper helpers, never hardcode.
- **No network by default.** Set `permissions.network: true` only if the skill truly needs it.
- **Tool-gate aware.** Only request tools that appear in `kidecon.yaml` `tool_gate.allow`.
- **Sandbox-safe.** Skills run under `UserScriptSandbox` — they get a 60s timeout and first-run approval.

## Contributing

1. Fork the repo and create `skills/<your_skill>/` (underscores, not hyphens).
2. Fill in `skill.yaml`, `README.md`, `handler.py`.
3. Test locally: `python -c "import importlib.util,sys; spec=importlib.util.spec_from_file_location('h','skills/<your-skill>/handler.py'); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m); print(m.run([], {}))"`.
4. Publish via `kidecon skills publish` (hub submission endpoint TBD).
