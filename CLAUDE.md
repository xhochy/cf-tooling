# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Purpose

This repository contains tooling for conda-forge maintenance tasks, primarily focused on creating and managing package migrations for the conda-forge ecosystem.

## Environment Setup

This project uses Pixi for dependency management:

```bash
# Install dependencies (handled by pixi automatically)
pixi install

# Run Python scripts in the pixi environment
pixi run python make_aws_migration.py
```

Dependencies are defined in `pixi.toml` and include:
- Python 3.14
- requests (for API calls to anaconda.org)
- pyyaml (for parsing conda-forge-pinning YAML configs)
- packaging (for version comparison)

## Key Tools

### make_aws_migration.py

Automates the creation of AWS C library migration PRs for conda-forge-pinning-feedstock:

1. Queries anaconda.org API to find latest package versions
2. Compares with pinned versions in `conda-forge-pinning-feedstock/recipe/conda_build_config.yaml`
3. Forks the pinning feedstock using `gh repo fork`
4. Creates a new branch based on `upstream/main`
5. Generates migration YAML file in `recipe/migrations/`
6. Commits, pushes, and creates a pull request

**Key implementation details:**
- Package names use hyphens (e.g., `aws-c-common`) when querying the API
- Config keys and YAML output use underscores (e.g., `aws_c_common`) per conda-forge convention
- Branch and file naming: `aws_c_<sanitized_suffix>` (spaces → underscores, non-alphanumeric removed)
- Uses `git -C` for repo operations, requiring relative paths (not absolute) for git commands
- Migration YAML format includes `__migrator` metadata, `migrator_ts` timestamp, and package versions

### gh-pr.sh

Zsh function to quickly checkout GitHub PRs locally:

```bash
# Usage
gh-pr https://github.com/owner/repo/pull/123
```

- Forks and clones repo if not present locally
- Strips URL fragments (e.g., `#issuecomment-xxx`) before parsing
- Fetches from upstream and checks out the PR branch
- Changes working directory to the repo

## Working with conda-forge Migrations

Migration files follow this structure:

```yaml
__migrator:
  build_number: 1
  commit_message: Rebuild for aws-c-* (reason)
  kind: version
  migration_number: 1
  exclude_pinned_pkgs: false
  automerge: true
migrator_ts: 1234567890
package_name:
  - 'version'
```

When creating new migration tools, follow the pattern established in `make_aws_migration.py`:
- Check existing versions from `conda_build_config.yaml`
- Use `packaging.version.parse()` for version comparison (not conda's VersionOrder)
- Handle both single values and list formats in YAML configs
- Generate timestamped migrations with proper metadata
