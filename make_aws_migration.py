import requests
import time
import yaml
import subprocess
import re
import os
from packaging.version import parse as parse_version



def get_most_recent_version(name):
    request = requests.get("https://api.anaconda.org/package/conda-forge/" + name)
    request.raise_for_status()
    files = request.json()["files"]
    files = [f for f in files if "broken" not in f.get("labels", ())]
    pkg = max(files, key=lambda x: parse_version(x["version"]))

    return pkg["version"]


packages = [
    "aws-c-auth",
    "aws-c-cal",
    "aws-c-common",
    "aws-c-compression",
    "aws-c-event-stream",
    "aws-c-http",
    "aws-c-io",
    "aws-c-mqtt",
    "aws-c-s3",
    "aws-c-sdkutils",
    "aws-checksums",
    "aws-crt-cpp",
    "s2n",
]

# Get user input for migration hint
migration_hint = input("Migration hint: ")

# Create sanitized suffix for branch and file names
# Replace spaces with underscores and remove non-alphanumeric characters
suffix = migration_hint.replace(' ', '_')
suffix = re.sub(r'[^a-zA-Z0-9_]', '', suffix)
branch_name = f"aws_c_{suffix}"
migration_filename = f"aws_c_{suffix}.yaml"

print(f"\nBranch name: {branch_name}")
print(f"Migration file: {migration_filename}\n")

# Fork and clone the pinning feedstock
repo_name = "conda-forge/conda-forge-pinning-feedstock"
repo_path = "conda-forge-pinning-feedstock"

if os.path.exists(repo_path):
    print("Repository already exists, updating...")
    subprocess.run(["git", "-C", repo_path, "fetch", "upstream"], check=True)
    subprocess.run(["git", "-C", repo_path, "checkout", "main"], check=True)
    subprocess.run(["git", "-C", repo_path, "merge", "upstream/main"], check=True)
else:
    print("Forking and cloning repository...")
    subprocess.run(["gh", "repo", "fork", repo_name, "--clone"], check=True)

# Create new branch based on upstream/main
print(f"Creating branch {branch_name} based on upstream/main...")
subprocess.run(["git", "-C", repo_path, "checkout", "-b", branch_name, "upstream/main"], check=True)

# Get config from local file
with open(os.path.join(repo_path, "recipe", "conda_build_config.yaml"), "r") as f:
    config = yaml.safe_load(f)

# Check each package for version updates
updated_packages = {}
for package in packages:
    # Convert hyphens to underscores for config lookup
    config_key = package.replace('-', '_')
    current_version = config.get(config_key)
    if current_version:
        # Handle list format in YAML (e.g., package: ['1.2.3'])
        if isinstance(current_version, list):
            current_version = current_version[0]

        latest_version = get_most_recent_version(package)

        if parse_version(latest_version) > parse_version(current_version):
            updated_packages[config_key] = latest_version
            print(f"Update available for {package}: {current_version} -> {latest_version}")
        else:
            print(f"No update for {package}: {current_version} is current")

# Generate migration content
migration = f"""__migrator:
  build_number: 1
  commit_message: Rebuild for aws-c-* ({migration_hint})
  kind: version
  migration_number: 1
  exclude_pinned_pkgs: false
  automerge: true
migrator_ts: {time.time():.0f}
"""

# Add updated packages to migration
for package, version in updated_packages.items():
    migration += f"{package}:\n  - '{version}'\n"

# Write migration file
migration_file_path = os.path.join(repo_path, "recipe", "migrations", migration_filename)
with open(migration_file_path, "w") as f:
    f.write(migration)

print(f"\nMigration written to {migration_file_path}")
print("\nMigration content:")
print(migration)

# Commit and push changes
print("\nCommitting changes...")
# Use relative path for git add since we're using -C to change directory
relative_migration_path = os.path.join("recipe", "migrations", migration_filename)
subprocess.run(["git", "-C", repo_path, "add", relative_migration_path], check=True)
commit_message = f"Add AWS C library migration: {migration_hint}"
subprocess.run(["git", "-C", repo_path, "commit", "-m", commit_message], check=True)

print(f"Pushing branch {branch_name} to origin...")
subprocess.run(["git", "-C", repo_path, "push", "-u", "origin", branch_name], check=True)

# Create pull request
print("\nCreating pull request...")
pr_title = f"Migrate for aws-c-* {migration_hint}"
pr_body = f"""aws-c-* migration for {migration_hint}

## Updated packages:
"""
for package, version in updated_packages.items():
    pr_body += f"- {package}: {version}\n"

pr_result = subprocess.run(
    ["gh", "pr", "create", "-R", repo_name, "--title", pr_title, "--body", pr_body],
    cwd=repo_path,
    capture_output=True,
    text=True,
    check=True
)

print(f"\nPull request created: {pr_result.stdout}")
