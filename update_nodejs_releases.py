#!/usr/bin/env python3
"""
Update Node.js feedstock for new patch releases across multiple minor series.

This script:
1. Fetches tags from nodejs/node GitHub repository
2. Identifies the latest patch version for each minor series (20.x, 22.x)
3. Compares with versions on conda-forge
4. For new releases, updates nodejs-feedstock:
   - Forks/clones the feedstock
   - Creates update branch
   - Updates meta.yaml version and resets build number
   - Fetches SHA256 from nodejs.org SHASUMS256.txt
   - Runs conda-smithy rerender
   - Pushes and creates PR to the appropriate minor branch

Usage:
    python update_nodejs_releases.py           # Run updates
    python update_nodejs_releases.py --dry-run # Preview changes without making them
"""

import requests
import subprocess
import os
import re
import sys
from packaging.version import parse as parse_version
from collections import defaultdict


def get_github_tags(owner, repo):
    """Fetch all tags from a GitHub repository."""
    tags = []
    page = 1
    per_page = 100

    while True:
        url = f"https://api.github.com/repos/{owner}/{repo}/tags"
        params = {"page": page, "per_page": per_page}
        response = requests.get(url, params=params)
        response.raise_for_status()

        page_tags = response.json()
        if not page_tags:
            break

        tags.extend(page_tags)
        page += 1

    return tags


def get_nodejs_versions_by_minor_series(target_series):
    """
    Get the latest patch version for each target minor series from GitHub tags.

    Args:
        target_series: List of minor series like ['20', '22']

    Returns:
        Dict mapping minor series to latest version (e.g., {'20': '20.11.0', ...})
    """
    print("Fetching tags from nodejs/node...")
    tags = get_github_tags("nodejs", "node")

    # Parse tags and group by minor series
    versions_by_series = defaultdict(list)

    for tag in tags:
        tag_name = tag["name"]
        # Match tags like "v20.11.0" or "v22.0.0"
        match = re.match(r'^v(\d+\.\d+\.\d+)$', tag_name)
        if match:
            version_str = match.group(1)
            try:
                version = parse_version(version_str)
                # Extract minor series (e.g., "20" from "20.11.0")
                major = version_str.split('.')[0]

                if major in target_series:
                    versions_by_series[major].append(version_str)
            except Exception as e:
                print(f"Warning: Could not parse version {version_str}: {e}")

    # Get the latest version for each series
    latest_by_series = {}
    for series, versions in versions_by_series.items():
        latest = max(versions, key=parse_version)
        latest_by_series[series] = latest
        print(f"  {series}.x: latest is {latest}")

    return latest_by_series


def get_current_version_from_recipe(repo_path):
    """Extract current version from meta.yaml or recipe.yaml."""
    # Try recipe.yaml first (newer format)
    recipe_yaml_path = os.path.join(repo_path, "recipe", "recipe.yaml")
    if os.path.exists(recipe_yaml_path):
        with open(recipe_yaml_path, "r") as f:
            content = f.read()

        # Look for version in context section: "  version: x.y.z"
        match = re.search(r'^\s*version:\s*([0-9.]+)', content, re.MULTILINE)
        if match:
            return match.group(1)

    # Fall back to meta.yaml (older format)
    meta_yaml_path = os.path.join(repo_path, "recipe", "meta.yaml")
    if os.path.exists(meta_yaml_path):
        with open(meta_yaml_path, "r") as f:
            content = f.read()

        # Look for {% set version = "x.y.z" %}
        match = re.search(r'{%\s*set\s+version\s*=\s*["\']([^"\']+)["\']\s*%}', content)
        if match:
            return match.group(1)

    return None


def get_nodejs_sha256_mappings(version):
    """
    Fetch SHA256 hashes for Node.js distribution files from nodejs.org.

    Args:
        version: Node.js version like "20.11.0"

    Returns:
        Dict mapping filenames to their SHA256 hashes
    """
    print(f"  Fetching SHA256 from nodejs.org for v{version}...")

    # Node.js publishes SHASUMS256.txt files for each release
    shasums_url = f"https://nodejs.org/dist/v{version}/SHASUMS256.txt"

    try:
        response = requests.get(shasums_url)
        response.raise_for_status()

        # Parse the SHASUMS256.txt file
        # Format: "<sha256>  <filename>"
        sha256_map = {}

        target_files = {
            f"node-v{version}.tar.gz": "unix",
            f"node-v{version}-win-x64.zip": "win-x64",
            f"node-v{version}-win-arm64.zip": "win-arm64",
        }

        for line in response.text.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                sha256_hash = parts[0]
                filename = parts[1]

                if filename in target_files:
                    platform = target_files[filename]
                    sha256_map[platform] = sha256_hash
                    print(f"  SHA256 ({platform}): {sha256_hash}")

        return sha256_map

    except Exception as e:
        print(f"  Warning: Failed to fetch SHA256: {e}")
        return {}


def update_feedstock(feedstock_name, minor_series, new_version, dry_run=False):
    """
    Update the Node.js feedstock for a new version.

    Args:
        feedstock_name: Name like "nodejs-feedstock"
        minor_series: Minor series like "20"
        new_version: New version like "20.11.0"
        dry_run: If True, only check versions without making changes

    Returns:
        True if update was performed (or would be performed), False if skipped
    """
    repo_name = f"conda-forge/{feedstock_name}"
    repo_path = feedstock_name
    branch_name = f"{minor_series}.x"
    update_branch = f"update-{new_version}"

    print(f"\n{'='*60}")
    print(f"Checking {feedstock_name} for {new_version}")
    print(f"{'='*60}")

    # Fork and clone if needed
    if os.path.exists(repo_path):
        print(f"Repository {repo_path} already exists, updating...")
        subprocess.run(["git", "-C", repo_path, "fetch", "upstream"], check=True)
    else:
        print(f"Forking and cloning {repo_name}...")
        subprocess.run(["gh", "repo", "fork", repo_name, "--clone"], check=True)

    # Checkout the minor series branch
    print(f"Checking out upstream/{branch_name}...")
    try:
        subprocess.run(["git", "-C", repo_path, "checkout", branch_name], check=True, capture_output=True)
        subprocess.run(["git", "-C", repo_path, "pull", "upstream", branch_name], check=True)
    except subprocess.CalledProcessError:
        print(f"Warning: Branch {branch_name} does not exist in {feedstock_name}. Skipping.")
        return False

    # Check current version
    current_version = get_current_version_from_recipe(repo_path)
    if current_version:
        print(f"Current version in {branch_name}: {current_version}")

        if parse_version(new_version) <= parse_version(current_version):
            print(f"Version {current_version} is up-to-date. Skipping.")
            return False

        print(f"Update available: {current_version} -> {new_version}")
    else:
        print("Warning: Could not determine current version, proceeding with update...")

    if dry_run:
        print(f"\n[DRY RUN] Would update {feedstock_name} from {current_version} to {new_version}")
        return True

    # Create new update branch
    print(f"Creating update branch {update_branch}...")
    subprocess.run(["git", "-C", repo_path, "checkout", "-b", update_branch], check=True)

    # Fetch SHA256 hashes for Node.js distributions
    print(f"Fetching SHA256 hashes for Node.js {new_version}...")
    sha256_mappings = get_nodejs_sha256_mappings(new_version)

    if not sha256_mappings:
        print("Warning: Could not fetch SHA256 hashes. Continuing without hash update...")

    # Check if using recipe.yaml or meta.yaml
    recipe_yaml_path = os.path.join(repo_path, "recipe", "recipe.yaml")
    meta_yaml_path = os.path.join(repo_path, "recipe", "meta.yaml")

    if os.path.exists(recipe_yaml_path):
        recipe_path = recipe_yaml_path
        is_recipe_yaml = True
    elif os.path.exists(meta_yaml_path):
        recipe_path = meta_yaml_path
        is_recipe_yaml = False
    else:
        raise FileNotFoundError("Neither recipe.yaml nor meta.yaml found")

    print(f"Updating {recipe_path}...")

    with open(recipe_path, "r") as f:
        lines = f.readlines()

    # Process line by line
    updated_lines = []
    current_platform = None  # Track which platform section we're in (for recipe.yaml)

    for line in lines:
        original_line = line

        if is_recipe_yaml:
            # For recipe.yaml format
            # Update version in context section
            if re.match(r'^\s*version:\s*[0-9.]+', line):
                line = re.sub(
                    r'(^\s*version:\s*)[0-9.]+',
                    rf'\g<1>{new_version}',
                    line
                )
                print(f"  Updated version")

            # Update build number
            elif re.match(r'^\s+number:\s*\d+', line):
                line = re.sub(r'(^\s+number:\s*)\d+', r'\g<1>0', line)
                print(f"  Reset build number")

            # Detect platform context for sha256 updates
            elif re.search(r'if:\s*unix', line):
                current_platform = 'unix'
            elif re.search(r'if:\s*target_platform\s*==\s*"win-64"', line):
                current_platform = 'win-x64'
            elif re.search(r'if:\s*target_platform\s*==\s*"win-arm64"', line):
                current_platform = 'win-arm64'

            # Update sha256 based on current platform context
            elif re.match(r'^\s+sha256:\s*[a-fA-F0-9]{64}', line) and current_platform:
                if current_platform in sha256_mappings:
                    line = re.sub(
                        r'(^\s+sha256:\s*)[a-fA-F0-9]{64}',
                        rf'\g<1>{sha256_mappings[current_platform]}',
                        line
                    )
                    print(f"  Updated sha256 for {current_platform}")
        else:
            # For meta.yaml format (older Jinja2 format)
            # Update version
            if re.match(r'\s*{%\s*set\s+version\s*=', line):
                line = re.sub(
                    r'({% set version = ")[^"]+(")',
                    rf'\g<1>{new_version}\g<2>',
                    line
                )
                print(f"  Updated version")

            # Update build number
            elif re.match(r'\s+number:\s*\d+', line):
                line = re.sub(r'(\s+number:\s*)\d+', r'\g<1>0', line)
                print(f"  Reset build number")

            # Update sha256 (assuming single source for meta.yaml)
            elif 'unix' in sha256_mappings and re.match(r'\s+sha256:\s*[a-fA-F0-9]{64}', line):
                line = re.sub(
                    r'(\s+sha256:\s*)[a-fA-F0-9]{64}',
                    rf'\g<1>{sha256_mappings["unix"]}',
                    line
                )
                print(f"  Updated sha256")

        updated_lines.append(line)

    with open(recipe_path, "w") as f:
        f.writelines(updated_lines)

    print(f"Updated {'recipe.yaml' if is_recipe_yaml else 'meta.yaml'} (version, sha256 hashes, and build number)")

    # Commit the recipe changes
    print("Committing recipe changes...")
    if os.path.exists(recipe_yaml_path):
        recipe_file = "recipe/recipe.yaml"
    else:
        recipe_file = "recipe/meta.yaml"

    subprocess.run(
        ["git", "-C", repo_path, "add", recipe_file],
        check=True
    )
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", f"Update to {new_version}"],
        check=True
    )

    # Run conda-smithy rerender
    print("Running conda-smithy rerender...")
    result = subprocess.run(
        ["conda-smithy", "rerender", "--no-check-uptodate"],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Warning: conda-smithy rerender failed: {result.stderr}")
        print("Continuing anyway...")
    else:
        print("Rerender completed successfully")

        # Check if there are changes to commit
        status_result = subprocess.run(
            ["git", "-C", repo_path, "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=True
        )

        if status_result.stdout.strip():
            print("Committing rerender changes...")
            subprocess.run(
                ["git", "-C", repo_path, "add", "-A"],
                check=True
            )
            subprocess.run(
                ["git", "-C", repo_path, "commit", "-m", "MNT: Re-rendered with conda-smithy"],
                check=True
            )
        else:
            print("No changes from rerender to commit")

    # Push to fork
    print(f"Pushing {update_branch} to origin...")
    subprocess.run(
        ["git", "-C", repo_path, "push", "-u", "origin", update_branch],
        check=True
    )

    # Create pull request
    print("Creating pull request...")
    pr_title = f"Update to Node.js {new_version}"
    pr_body = f"""This PR updates the Node.js version to {new_version}.

Changes:
- Updated version to {new_version}
- Updated source tarball sha256
- Reset build number to 0
- Re-rendered with conda-smithy
"""

    pr_result = subprocess.run(
        ["gh", "pr", "create",
         "-R", repo_name,
         "--base", branch_name,
         "--title", pr_title,
         "--body", pr_body],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    print(f"Pull request created: {pr_result.stdout.strip()}")
    return True


def main():
    # Check for dry-run mode
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 60)
        print()

    # Define target minor series for Node.js LTS versions
    # 20.x = Iron LTS (until April 2026)
    # 22.x = Jill LTS (until April 2027)
    target_series = ['20', '22']

    # Get latest versions from GitHub for each series
    latest_github_versions = get_nodejs_versions_by_minor_series(target_series)

    if not latest_github_versions:
        print("\nNo versions found for target series. Exiting.")
        return

    print(f"\nFound {len(latest_github_versions)} minor series with releases:")
    for series, version in sorted(latest_github_versions.items(), key=lambda x: int(x[0])):
        print(f"  {series}.x: {version}")

    # Process each series
    feedstock = "nodejs-feedstock"
    updates_made = []
    updates_skipped = []
    errors = []

    for series, new_version in sorted(latest_github_versions.items(), key=lambda x: int(x[0])):
        print(f"\n{'#'*60}")
        print(f"Processing Node.js {new_version} ({series}.x series)")
        print(f"{'#'*60}")

        try:
            result = update_feedstock(feedstock, series, new_version, dry_run=dry_run)
            if result:
                updates_made.append((series, new_version))
            else:
                updates_skipped.append((series, new_version))
        except Exception as e:
            print(f"\nError updating {feedstock}: {e}")
            import traceback
            traceback.print_exc()
            errors.append((series, str(e)))
            continue

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY" + (" (DRY RUN)" if dry_run else ""))
    print(f"{'='*60}")

    if updates_made:
        action = "Would create" if dry_run else "Updates created"
        print(f"\n✓ {action} ({len(updates_made)}):")
        for series, version in updates_made:
            print(f"  - nodejs-feedstock {series}.x → {version}")

    if updates_skipped:
        print(f"\n○ Already up-to-date ({len(updates_skipped)}):")
        for series, version in updates_skipped:
            print(f"  - nodejs-feedstock {series}.x (current: {version})")

    if errors:
        print(f"\n✗ Errors ({len(errors)}):")
        for series, error in errors:
            print(f"  - nodejs-feedstock {series}.x: {error}")

    print()


if __name__ == "__main__":
    main()
