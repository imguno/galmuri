"""Disposable real PostgreSQL schemas and subprocess controls."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from tools.multi_instance_acceptance.fixture import publish


class Process:
    def __init__(self, configuration, directory, action):
        self.directory = directory
        directory.mkdir()
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "tools.multi_instance_acceptance.worker",
                str(configuration),
                str(directory),
                action,
            ],
            cwd=Path(__file__).resolve().parents[2],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
        )

    def wait_file(self, name):
        deadline = time.monotonic() + 30
        path = self.directory / name
        while True:
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (FileNotFoundError, PermissionError) as error:
                # A Windows sharing lock can outlast atomic rename visibility.
                # Reading is the barrier; existence alone is not enough.
                pending = error
            if self.process.poll() is not None:
                raise AssertionError("Worker exited early: " + self.process.communicate()[0])
            if time.monotonic() >= deadline:
                raise AssertionError("Worker did not reach " + name) from pending
            time.sleep(0.02)

    def signal(self, name):
        (self.directory / name).touch()

    def finish(self):
        output, _ = self.process.communicate(timeout=30)
        assert self.process.returncode == 0, output

    def stop(self):
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)
        if self.process.stdout:
            self.process.stdout.close()


@pytest.fixture
def scenario(tmp_path):
    driver = pytest.importorskip("psycopg")
    dsn = os.environ.get("FRAMEWORK_POSTGRES_DSN")
    if not dsn:
        pytest.skip("FRAMEWORK_POSTGRES_DSN is not configured")
    config = {"schema": "test_process_" + uuid4().hex, "source": str(tmp_path / "source.json")}
    configuration = tmp_path / "configuration.json"
    processes = []

    def start(action, *, lease_seconds=30):
        config["lease_seconds"] = lease_seconds
        publish(configuration, config)
        process = Process(configuration, tmp_path / f"worker_{len(processes)}", action)
        processes.append(process)
        return process

    yield config, start
    for process in processes:
        process.stop()
    with driver.connect(dsn, autocommit=True) as connection:
        for schema in (config["schema"], *config.get("extra_schemas", ())):
            connection.execute('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE')
