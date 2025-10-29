import requests
import time
import yaml
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

r = requests.get("https://raw.githubusercontent.com/conda-forge/conda-forge-pinning-feedstock/refs/heads/main/recipe/conda_build_config.yaml")
r.raise_for_status()

config = yaml.safe_load(r.text)

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

migration = f"""__migrator:
  build_number: 1
  commit_message: Rebuild for aws-c-* ({input("Migration hint: ")})
  kind: version
  migration_number: 1
  exclude_pinned_pkgs: false
  automerge: true
migrator_ts: {time.time():.0f}
"""

# Add updated packages to migration
for package, version in updated_packages.items():
    migration += f"{package}:\n  - '{version}'\n"

print("\n" + migration)
