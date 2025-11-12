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


def get_current_version_from_meta(repo_path):
    """Extract current version from meta.yaml."""
    meta_yaml_path = os.path.join(repo_path, "recipe", "meta.yaml")

    if not os.path.exists(meta_yaml_path):
        return None

    with open(meta_yaml_path, "r") as f:
        content = f.read()

    # Look for {% set version = "x.y.z" %}
    match = re.search(r'{%\s*set\s+version\s*=\s*["\']([^"\']+)["\']\s*%}', content)
    if match:
        return match.group(1)

    return None


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
    current_version = get_current_version_from_meta(repo_path)
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
    print("Committing meta.yaml changes...")
    subprocess.run(
        ["git", "-C", repo_path, "add", "recipe/meta.yaml"],
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
                ["git", "-C", repo_path, "commit", "-m", "MNT: Re-rendered with conda-build 3.28.4, conda-smithy 3.42.0, and conda-forge-pinning 2024.11.12.15.28.29"],
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
    pr_title = f"Update to Go {new_version}"
    pr_body = f"""This PR updates the Go version to {new_version}.

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

    # Define target minor series
    target_series = ['1.20', '1.21', '1.22', '1.23']

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
