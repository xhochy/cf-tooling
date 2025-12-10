#!/usr/bin/env python3
"""
Shared utilities for updating conda-forge feedstocks.

This module provides common functions used by release automation scripts
for Go, Node.js, and other language ecosystems.
"""

import requests
import subprocess
import os
import re
from packaging.version import parse as parse_version


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


def get_current_version_from_recipe(repo_path):
    """
    Extract current version from recipe.yaml or meta.yaml.
    
    Supports both newer recipe.yaml format and older meta.yaml Jinja2 format.
    
    Args:
        repo_path: Path to the feedstock repository
        
    Returns:
        Version string or None if not found
    """
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


def fork_and_clone_feedstock(repo_name, repo_path):
    """
    Fork and clone a feedstock repository if it doesn't exist locally.
    
    Args:
        repo_name: Full repository name (e.g., "conda-forge/go-feedstock")
        repo_path: Local path where repository should be cloned
    """
    if os.path.exists(repo_path):
        print(f"Repository {repo_path} already exists, updating...")
        subprocess.run(["git", "-C", repo_path, "fetch", "upstream"], check=True)
    else:
        print(f"Forking and cloning {repo_name}...")
        subprocess.run(["gh", "repo", "fork", repo_name, "--clone"], check=True)


def checkout_branch(repo_path, branch_name):
    """
    Checkout a branch from upstream and pull latest changes.
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the branch to checkout
        
    Returns:
        True if successful, False if branch doesn't exist
    """
    print(f"Checking out upstream/{branch_name}...")
    try:
        subprocess.run(
            ["git", "-C", repo_path, "checkout", branch_name], 
            check=True, 
            capture_output=True
        )
        subprocess.run(
            ["git", "-C", repo_path, "pull", "upstream", branch_name], 
            check=True
        )
        return True
    except subprocess.CalledProcessError:
        return False


def create_update_branch(repo_path, branch_name):
    """
    Create a new branch for the update.
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the new branch
    """
    print(f"Creating update branch {branch_name}...")
    subprocess.run(
        ["git", "-C", repo_path, "checkout", "-b", branch_name], 
        check=True
    )


def commit_changes(repo_path, files, commit_message):
    """
    Stage and commit changes to specified files.
    
    Args:
        repo_path: Path to the repository
        files: List of file paths to add (relative to repo_path)
        commit_message: Commit message
    """
    print(f"Committing changes: {commit_message}")
    for file in files:
        subprocess.run(
            ["git", "-C", repo_path, "add", file],
            check=True
        )
    subprocess.run(
        ["git", "-C", repo_path, "commit", "-m", commit_message],
        check=True
    )


def run_conda_smithy_rerender(repo_path):
    """
    Run conda-smithy rerender and commit changes if any.
    
    Args:
        repo_path: Path to the repository
        
    Returns:
        True if rerender was successful, False otherwise
    """
    print("Running conda-smithy rerender...")
    result = subprocess.run(
        ["conda-smithy", "rerender", "--no-check-uptodate", "--commit", "auto"],
        cwd=repo_path,
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        print(f"Warning: conda-smithy rerender failed: {result.stderr}")
        print("Continuing anyway...")
        return False

    print("Rerender completed successfully")

    return True


def push_branch(repo_path, branch_name):
    """
    Push branch to origin (fork).
    
    Args:
        repo_path: Path to the repository
        branch_name: Name of the branch to push
    """
    print(f"Pushing {branch_name} to origin...")
    subprocess.run(
        ["git", "-C", repo_path, "push", "-u", "origin", branch_name],
        check=True
    )


def create_pull_request(repo_path, repo_name, base_branch, title, body, automerge: True):
    """
    Create a pull request using GitHub CLI.
    
    Args:
        repo_path: Path to the repository
        repo_name: Full repository name (e.g., "conda-forge/go-feedstock")
        base_branch: Base branch for the PR
        title: PR title
        body: PR body/description
        
    Returns:
        PR URL as string
    """
    print("Creating pull request...")
    args:list[str] = []
    if automerge:
        args.extend(["--label", "automerge"])
    pr_result = subprocess.run(
        ["gh", "pr", "create",
         "-R", repo_name,
         "--base", base_branch,
         "--title", title,
         "--body", body] + args,
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True
    )

    pr_url = pr_result.stdout.strip()
    print(f"Pull request created: {pr_url}")
    return pr_url


def check_version_needs_update(current_version, new_version):
    """
    Check if an update is needed based on version comparison.
    
    Args:
        current_version: Current version string
        new_version: New version string
        
    Returns:
        True if update is needed, False otherwise
    """
    if not current_version:
        print("Warning: Could not determine current version, proceeding with update...")
        return True
        
    print(f"Current version: {current_version}")
    
    if parse_version(new_version) <= parse_version(current_version):
        print(f"Version {current_version} is up-to-date. Skipping.")
        return False
    
    print(f"Update available: {current_version} -> {new_version}")
    return True
