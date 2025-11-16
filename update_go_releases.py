#!/usr/bin/env python3
"""
Update Go feedstocks for new patch releases across multiple minor series.

This script:
1. Fetches tags from golang/go GitHub repository
2. Identifies the latest patch version for each minor series (1.20.x, 1.21.x, 1.22.x, 1.23.x)
3. Compares with versions on conda-forge
4. For new releases, updates both go-feedstock and go-activation-feedstock:
   - Forks/clones the feedstocks
   - Creates update branch
   - Updates meta.yaml version and resets build number
   - Runs conda-smithy rerender
   - Pushes and creates PR to the appropriate minor branch

Usage:
    python update_go_releases.py           # Run updates
    python update_go_releases.py --dry-run # Preview changes without making them
"""

import requests
import subprocess
import os
import re
import sys
import yaml
import hashlib
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


def get_go_versions_by_minor_series(target_series):
    """
    Get the latest patch version for each target minor series from GitHub tags.

    Args:
        target_series: List of minor series like ['1.20', '1.21', '1.22', '1.23']

    Returns:
        Dict mapping minor series to latest version (e.g., {'1.20': '1.20.14', ...})
    """
    print("Fetching tags from golang/go...")
    tags = get_github_tags("golang", "go")

    # Parse tags and group by minor series
    versions_by_series = defaultdict(list)

    for tag in tags:
        tag_name = tag["name"]
        # Match tags like "go1.20.14" or "go1.21.0"
        match = re.match(r'^go(1\.\d+\.\d+)$', tag_name)
        if match:
            version_str = match.group(1)
            try:
                version = parse_version(version_str)
                # Extract minor series (e.g., "1.20" from "1.20.14")
                minor_series = '.'.join(version_str.split('.')[:2])

                if minor_series in target_series:
                    versions_by_series[minor_series].append(version_str)
            except Exception as e:
                print(f"Warning: Could not parse version {version_str}: {e}")

    # Get the latest version for each series
    latest_by_series = {}
    for series, versions in versions_by_series.items():
        latest = max(versions, key=parse_version)
        latest_by_series[series] = latest
        print(f"  {series}.x: latest is {latest}")

    return latest_by_series





def compute_sha256_from_url(url):
    """
    Compute SHA256 hash for a file from URL.

    Args:
        url: URL to download and hash

    Returns:
        SHA256 hash as hex string
    """
    print(f"  Fetching {url}...")

    response = requests.get(url, stream=True)
    response.raise_for_status()

    sha256_hash = hashlib.sha256()
    for chunk in response.iter_content(chunk_size=8192):
        sha256_hash.update(chunk)

    hash_value = sha256_hash.hexdigest()
    print(f"  SHA256: {hash_value}")
    return hash_value


def get_go_sha256_mappings(version):
    """
    Compute SHA256 hashes for all Go distribution files.

    Args:
        version: Go version like "1.23.12"

    Returns:
        Dict mapping URL patterns to their SHA256 hashes
    """
    print(f"Computing SHA256 hashes for Go {version} distributions...")

    urls = [
        f"https://dl.google.com/go/go{version}.src.tar.gz",
        f"https://go.dev/dl/go{version}.linux-amd64.tar.gz",
        f"https://go.dev/dl/go{version}.windows-amd64.zip",
        f"https://go.dev/dl/go{version}.darwin-amd64.tar.gz",
        f"https://go.dev/dl/go{version}.darwin-arm64.tar.gz",
    ]

    sha256_map = {}
    for url in urls:
        try:
            sha256_map[url] = compute_sha256_from_url(url)
        except Exception as e:
            print(f"  Warning: Failed to fetch {url}: {e}")
            continue

    return sha256_map


def update_feedstock(feedstock_name, minor_series, new_version, dry_run=False):
    """
    Update a Go feedstock for a new version.

    Args:
        feedstock_name: Name like "go-feedstock" or "go-activation-feedstock"
        minor_series: Minor series like "1.20"
        new_version: New version like "1.20.14"
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

    # Fetch SHA256 hashes for all Go distributions
    print(f"Fetching SHA256 hashes for Go {new_version}...")
    try:
        sha256_mappings = get_go_sha256_mappings(new_version)
        if not sha256_mappings:
            print("Warning: No SHA256 hashes computed")
    except Exception as e:
        print(f"Warning: Failed to fetch SHA256 hashes: {e}")
        print("Continuing without SHA256 update...")
        sha256_mappings = {}

    # Update meta.yaml
    meta_yaml_path = os.path.join(repo_path, "recipe", "meta.yaml")
    print(f"Updating {meta_yaml_path}...")

    with open(meta_yaml_path, "r") as f:
        lines = f.readlines()

    # Process line by line to update sha256 values correctly
    updated_lines = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Update version
        if re.match(r'\s*{%\s*set\s+version\s*=', line):
            line = re.sub(
                r'({% set version = ")[^"]+(")',
                rf'\g<1>{new_version}\g<2>',
                line
            )

        # Update build number
        elif re.match(r'\s+number:\s*\d+', line):
            line = re.sub(r'(\s+number:\s*)\d+', r'\g<1>0', line)

        # Update sha256 - look for URL on previous line(s)
        elif re.match(r'\s+sha256:\s*[a-fA-F0-9]{64}', line):
            # Search backwards for the corresponding URL
            url_found = None
            for j in range(i-1, max(0, i-10), -1):
                url_match = re.search(r'url:\s*(https://[^\s]+go' + re.escape(new_version) + r'[^\s]*)', lines[j])
                if not url_match:
                    # Also try with version/name placeholders
                    url_match = re.search(r'url:\s*(https://[^\s{]+(?:{{\s*\w+\s*}}[^\s{]*)+)', lines[j])
                    if url_match:
                        # Expand the URL template
                        url_template = url_match.group(1)
                        # Replace common Jinja2 variables
                        url_found = url_template.replace('{{ version }}', new_version).replace('{{version}}', new_version)
                        url_found = url_found.replace('{{ name }}', 'go').replace('{{name}}', 'go')
                        break
                else:
                    url_found = url_match.group(1)
                    break

            if url_found and url_found in sha256_mappings:
                new_sha256 = sha256_mappings[url_found]
                line = re.sub(
                    r'(\s+sha256:\s*)[a-fA-F0-9]{64}',
                    rf'\g<1>{new_sha256}',
                    line
                )
                print(f"  Updated sha256 for {url_found}")

        updated_lines.append(line)
        i += 1

    with open(meta_yaml_path, "w") as f:
        f.writelines(updated_lines)

    print("Updated meta.yaml (version, sha256 hashes, and build number)")

    # Commit the meta.yaml changes
    commit_changes(repo_path, ["recipe/meta.yaml"], f"Update to {new_version}")

    # Run conda-smithy rerender
    run_conda_smithy_rerender(repo_path)

    # Push to fork
    push_branch(repo_path, update_branch)

    # Create pull request
    pr_title = f"Update to Go {new_version}"
    pr_body = f"""This PR updates the Go version to {new_version}.

Changes:
- Updated version to {new_version}
- Updated source tarball sha256
- Reset build number to 0
- Re-rendered with conda-smithy
"""

    create_pull_request(repo_path, repo_name, branch_name, pr_title, pr_body)
    return True


def main():
    # Check for dry-run mode
    dry_run = "--dry-run" in sys.argv or "-n" in sys.argv

    if dry_run:
        print("=" * 60)
        print("DRY RUN MODE - No changes will be made")
        print("=" * 60)
        print()

    # Define target minor series
    target_series = ['1.20', '1.21', '1.22', '1.23', '1.24']

    # Get latest versions from GitHub for each series
    latest_github_versions = get_go_versions_by_minor_series(target_series)

    if not latest_github_versions:
        print("\nNo versions found for target series. Exiting.")
        return

    print(f"\nFound {len(latest_github_versions)} minor series with releases:")
    for series, version in sorted(latest_github_versions.items()):
        print(f"  {series}.x: {version}")

    # Note: We can't directly compare with conda-forge since it doesn't store per-minor-series
    # We'll assume any version we find on GitHub that we want to update is newer
    # In practice, you might want to check the existing branch's meta.yaml

    # Process each series
    feedstocks = ["go-feedstock", "go-activation-feedstock"]
    updates_made = []
    updates_skipped = []
    errors = []

    for series, new_version in sorted(latest_github_versions.items()):
        print(f"\n{'#'*60}")
        print(f"Processing Go {new_version} ({series}.x series)")
        print(f"{'#'*60}")

        for feedstock in feedstocks:
            try:
                result = update_feedstock(feedstock, series, new_version, dry_run=dry_run)
                if result:
                    updates_made.append((feedstock, series, new_version))
                else:
                    updates_skipped.append((feedstock, series, new_version))
            except Exception as e:
                print(f"\nError updating {feedstock}: {e}")
                print("Continuing with next feedstock...")
                errors.append((feedstock, series, str(e)))
                continue

    # Print summary
    print(f"\n{'='*60}")
    print("SUMMARY" + (" (DRY RUN)" if dry_run else ""))
    print(f"{'='*60}")

    if updates_made:
        action = "Would create" if dry_run else "Updates created"
        print(f"\n✓ {action} ({len(updates_made)}):")
        for feedstock, series, version in updates_made:
            print(f"  - {feedstock} {series}.x → {version}")

    if updates_skipped:
        print(f"\n○ Already up-to-date ({len(updates_skipped)}):")
        for feedstock, series, version in updates_skipped:
            print(f"  - {feedstock} {series}.x (current: {version})")

    if errors:
        print(f"\n✗ Errors ({len(errors)}):")
        for feedstock, series, error in errors:
            print(f"  - {feedstock} {series}.x: {error}")

    print()


if __name__ == "__main__":
    main()
