#!/usr/bin/env python3
"""
Upload a pi agent trace from a conda-forge session to Hugging Face.

Usage:
    pixi run python cf-hf-pi-trace.py <session_id>

Example:
    pixi run python cf-hf-pi-trace.py 019ed9c6-cd4d-7ebf-b021-e7fc0b392cb3
"""

import argparse
import sys
import subprocess
from pathlib import Path

PI_SESSIONS_DIR = Path("~/.pi/agent/sessions").expanduser()

HF_REPO = "xhochy/conda-forge-agent-traces"

def main():
    parser = argparse.ArgumentParser(
        description="Upload a pi agent trace from a conda-forge session to Hugging Face"
    )
    parser.add_argument("session_id", help="pi agent session ID (UUID format, e.g. 019ed9c6-cd4d-7ebf-b021-e7fc0b392cb3)")
    args = parser.parse_args()

    session_id = args.session_id.strip()

    # Validate session_id looks like a UUID (basic sanity check)
    if not (len(session_id) == 36 and session_id.count("-") == 4):
        sys.exit(f"Error: session ID '{session_id}' does not look like a valid UUID")

    # Search for the trace file in conda-forge session directories
    if not PI_SESSIONS_DIR.is_dir():
        sys.exit(f"Error: pi sessions directory not found at {PI_SESSIONS_DIR}")

    trace_path = None
    session_dir_name = None

    for entry in PI_SESSIONS_DIR.iterdir():
        if not entry.is_dir():
            continue

        dir_name = entry.name
        # Only consider directories under the conda-forge path
        if not dir_name.startswith("--Users-uwe.korn-Development-conda-forge"):
            continue

        # Look for a file ending with _<session_id>.jsonl
        for trace_file in entry.iterdir():
            if trace_file.name.endswith(f"_{session_id}.jsonl"):
                trace_path = trace_file
                session_dir_name = dir_name
                break

        if trace_path:
            break

    if trace_path is None:
        sys.exit(
            f"Error: no trace file found for session ID '{session_id}' "
            f"in any conda-forge session directory under {PI_SESSIONS_DIR}\n"
            f"Expected a directory matching --Users-uwe.korn-Development-conda-forge* "
            f"containing a file ending with _{session_id}.jsonl"
        )

    print(f"Found trace file: {trace_path}")
    print(f"Session directory: {session_dir_name}")

    # Upload to Hugging Face
    cmd = [
        "hf", "upload",
        HF_REPO,
        str(trace_path),
        "--repo-type=dataset",
    ]

    print(f"Uploading to https://huggingface.co/datasets/{HF_REPO} ...")
    result = subprocess.run(cmd, capture_output=False)

    if result.returncode != 0:
        sys.exit(f"Upload failed with exit code {result.returncode}")

    print("Upload successful!")

if __name__ == "__main__":
    main()
