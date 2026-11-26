"""Shared pytest fixtures for Docker-backed integration tests."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

import pytest

_EMULATORS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "emulators")


def _is_docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        res = subprocess.run(
            ["docker", "info"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        return res.returncode == 0
    except Exception:
        return False


def _start_emulator_container(
    script_name: str,
) -> Generator[dict[str, Any], None, None]:
    if not _is_docker_available():
        pytest.skip(
            "Docker is not available; skipping containerized integration tests."
        )

    run_cmd = [
        "docker",
        "run",
        "-d",
        "--rm",
        "-p",
        "0:8000",
        "-v",
        f"{_EMULATORS_DIR}:/emulators:ro",
        "python:3.12-slim",
        "python",
        f"/emulators/{script_name}",
    ]
    container_id: str | None = None
    try:
        proc = subprocess.run(run_cmd, capture_output=True, text=True, check=True)
        container_id = proc.stdout.strip()
    except subprocess.CalledProcessError as e:
        pytest.skip(f"Failed to start {script_name} container: {e.stderr}")

    if not container_id:
        pytest.skip(f"Failed to start {script_name} container: empty container ID.")

    try:
        port_proc = subprocess.run(
            ["docker", "port", container_id, "8000/tcp"],
            capture_output=True,
            text=True,
            check=True,
        )
        port_line = port_proc.stdout.strip().splitlines()[0]
        host_port = int(port_line.split(":")[-1])
        base_url = f"http://127.0.0.1:{host_port}"

        ready = False
        for _ in range(30):
            try:
                with urllib.request.urlopen(f"{base_url}/health", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.3)

        if not ready:
            pytest.fail(f"Timed out waiting for {script_name} container to start.")

        yield {"base_url": base_url, "container_id": container_id}
    finally:
        if container_id:
            subprocess.run(
                ["docker", "rm", "-f", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )


@pytest.fixture(scope="module")
def bitbucket_cloud_container() -> Generator[dict[str, Any], None, None]:
    """Spins up a containerized Bitbucket Cloud REST 2.0 emulator."""
    yield from _start_emulator_container("bitbucket_cloud_emulator.py")


@pytest.fixture(scope="module")
def github_container() -> Generator[dict[str, Any], None, None]:
    """Spins up a containerized GitHub REST v3 + GraphQL emulator."""
    yield from _start_emulator_container("github_emulator.py")
