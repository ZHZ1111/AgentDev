"""Host-loaded pytest hooks for D1; no model output or console parsing."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


class _Recorder:
    def __init__(self, destination: Path) -> None:
        self.destination = destination
        self.data = {
            "schema_version": 1,
            "items": None,
            "reports": [],
            "collection_errors": [],
            "completed": False,
            "exit_code": None,
        }

    def save(self) -> None:
        # Replace atomically so a timed-out process leaves the last full checkpoint.
        temporary = self.destination.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.destination)

    def pytest_sessionstart(self, session) -> None:
        self.save()

    def pytest_collection_finish(self, session) -> None:
        self.data["items"] = [item.nodeid for item in session.items]
        self.save()

    def pytest_collectreport(self, report) -> None:
        if report.failed:
            self.data["collection_errors"].append({
                "nodeid": report.nodeid,
                "detail": str(report.longrepr),
            })
            self.save()

    @pytest.hookimpl(hookwrapper=True, tryfirst=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        report = outcome.get_result()
        # pytest.fail()/raises failures and strict XPASS are pytest failures;
        # exceptions such as ValueError in the test call are execution errors.
        report.testgen_assertion = (
            call.excinfo is None
            or call.excinfo.errisinstance((AssertionError, pytest.fail.Exception))
        )

    def pytest_runtest_logreport(self, report) -> None:
        self.data["reports"].append({
            "nodeid": report.nodeid,
            "when": report.when,
            "outcome": report.outcome,
            "assertion": getattr(report, "testgen_assertion", False),
            "xfail": hasattr(report, "wasxfail"),
            "location": list(report.location),
            "detail": str(report.longrepr) if report.failed or report.skipped else "",
        })
        self.save()

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session, exitstatus) -> None:
        self.data["completed"] = True
        self.data["exit_code"] = int(exitstatus)
        self.save()


def pytest_configure(config) -> None:
    destination = Path(os.environ["TESTGEN_EXECUTION_REPORT"])
    config.pluginmanager.register(_Recorder(destination), "testgen-result-recorder")
