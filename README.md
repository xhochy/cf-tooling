# conda-forge tooling

Minimal personal tools to make me more productive with conda-forge maintenance tasks.

## Setup

```bash
pixi install
```

## Tools

### Release Automation Scripts

- **update_go_releases.py** - Automate Go feedstock updates for new patch releases
- **update_nodejs_releases.py** - Automate Node.js feedstock updates for new patch releases
- **feedstock_utils.py** - Shared utilities for feedstock automation (used by release scripts)

### Migration and Utilities

- **make_aws_migration.py** - Automate AWS C library migration PRs for conda-forge-pinning
- **gh-pr.sh** - Quickly checkout GitHub PRs locally (`gh-pr <pr-url>`)

See [CLAUDE.md](CLAUDE.md) for detailed documentation.
