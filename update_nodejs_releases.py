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
from feedstock_utils import (
    get_github_tags,
    get_current_version_from_recipe,
    fork_and_clone_feedstock,
    checkout_branch,
    create_update_branch,
    commit_changes,
    run_conda_smithy_rerender,
    push_branch,
    create_pull_request,
    check_version_needs_update
)


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
    fork_and_clone_feedstock(repo_name, repo_path)

    # Checkout the minor series branch
    if not checkout_branch(repo_path, branch_name):
        print(f"Warning: Branch {branch_name} does not exist in {feedstock_name}. Skipping.")
        return False

    # Check current version
    current_version = get_current_version_from_recipe(repo_path)
    print(f"Current version in {branch_name}: {current_version}")
    
    if not check_version_needs_update(current_version, new_version):
        return False

    if dry_run:
        print(f"\n[DRY RUN] Would update {feedstock_name} from {current_version} to {new_version}")
        return True

    # Create new update branch
    create_update_branch(repo_path, update_branch)

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
            if re.match(r'^\s*version:\s*["\']?[0-9.]+', line):
                line = re.sub(
                    r'(^\s*version:\s*["\']?)[0-9.]+(["\']?)',
                    rf'\g<1>{new_version}\g<2>',
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

            # Update sha256 based on platform selector
            elif re.match(r'\s+sha256:\s*[a-fA-F0-9]{64}', line):
                # Detect platform from inline selector comment
                platform_key = None
                if '# [unix]' in line or '# [not win]' in line:
                    platform_key = 'unix'
                elif '# [target_platform == "win-64"]' in line or '# [win64]' in line:
                    platform_key = 'win-x64'
                elif '# [target_platform == "win-arm64"]' in line or '# [win-arm64]' in line:
                    platform_key = 'win-arm64'

                if platform_key and platform_key in sha256_mappings:
                    line = re.sub(
                        r'(\s+sha256:\s*)[a-fA-F0-9]{64}',
                        rf'\g<1>{sha256_mappings[platform_key]}',
                        line
                    )
                    print(f"  Updated sha256 for {platform_key}")

        updated_lines.append(line)

    with open(recipe_path, "w") as f:
        f.writelines(updated_lines)

    print(f"Updated {'recipe.yaml' if is_recipe_yaml else 'meta.yaml'} (version, sha256 hashes, and build number)")

    # Commit the recipe changes
    recipe_file = "recipe/recipe.yaml" if os.path.exists(recipe_yaml_path) else "recipe/meta.yaml"
    commit_changes(repo_path, [recipe_file], f"Update to {new_version}")

    # Run conda-smithy rerender
    run_conda_smithy_rerender(repo_path)

    # Push to fork
    push_branch(repo_path, update_branch)

    # Create pull request
    pr_title = f"Update to Node.js {new_version}"
    pr_body = f"""This PR updates the Node.js version to {new_version}.

Changes:
- Updated version to {new_version}
- Updated source tarball sha256
- Reset build number to 0
- Re-rendered with conda-smithy
"""

    create_pull_request(repo_path, repo_name, branch_name, pr_title, pr_body, automerge=True)
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
    # 24.x = Krypton LTS (until April 2028)
    target_series = ['20', '22', '24']

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
