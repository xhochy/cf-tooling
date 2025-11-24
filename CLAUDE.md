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

### feedstock_utils.py

Shared utility module providing common functions for feedstock automation:

**Common operations:**
- `get_github_tags(owner, repo)` - Fetch all tags from a GitHub repository with pagination
- `get_current_version_from_recipe(repo_path)` - Extract version from recipe.yaml or meta.yaml
- `fork_and_clone_feedstock(repo_name, repo_path)` - Fork and clone a feedstock if needed
- `checkout_branch(repo_path, branch_name)` - Checkout and pull a branch from upstream
- `create_update_branch(repo_path, branch_name)` - Create a new branch for updates
- `commit_changes(repo_path, files, message)` - Stage and commit specified files
- `run_conda_smithy_rerender(repo_path)` - Run conda-smithy rerender and commit changes
- `push_branch(repo_path, branch_name)` - Push a branch to origin (fork)
- `create_pull_request(repo_path, repo_name, base_branch, title, body)` - Create a PR via GitHub CLI
- `check_version_needs_update(current_version, new_version)` - Compare versions to determine if update is needed

**Design principles:**
- Handles both recipe.yaml (newer format) and meta.yaml (Jinja2 format)
- Uses subprocess for git operations with relative paths (git -C)
- Provides consistent error handling and logging
- Returns boolean/data to allow callers to handle errors appropriately

### update_go_releases.py

Automates Go feedstock updates across multiple minor series (1.20.x, 1.21.x, etc.).

**Key features:**
- Fetches latest patch versions from golang/go GitHub tags
- Updates both go-feedstock and go-activation-feedstock
- Downloads distribution files to compute SHA256 hashes
- Supports multiple Go distributions (source, linux, windows, darwin for amd64/arm64)
- Creates PRs to minor-series-specific branches (e.g., 1.20.x, 1.21.x)

**Usage:**
```bash
pixi run python update_go_releases.py           # Run updates
pixi run python update_go_releases.py --dry-run # Preview changes
```

### update_nodejs_releases.py

Automates Node.js feedstock updates across multiple minor series (20.x, 22.x).

**Key features:**
- Fetches latest patch versions from nodejs/node GitHub tags
- Updates nodejs-feedstock for LTS versions
- Fetches SHA256 hashes from nodejs.org SHASUMS256.txt
- Handles both recipe.yaml (newer) and meta.yaml (older) formats
- Creates PRs to minor-series-specific branches (e.g., 20.x, 22.x)

**Usage:**
```bash
pixi run python update_nodejs_releases.py           # Run updates
pixi run python update_nodejs_releases.py --dry-run # Preview changes
```

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
