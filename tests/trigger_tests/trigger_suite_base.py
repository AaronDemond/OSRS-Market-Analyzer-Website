from pathlib import Path

from django.test import TestCase
from django.utils import timezone


class TriggerReportMixin(TestCase):
    REPORT_PATH = None
    REPORT_TITLE = ""
    REPORT_SCOPE = ""
    REPORT_CASES = []

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.REPORT_CASES = []
        cls._write_report(reset=True)

    @classmethod
    def tearDownClass(cls):
        cls._write_report(summary=True)
        super().tearDownClass()

    @classmethod
    def _write_report(cls, reset=False, summary=False):
        if cls.REPORT_PATH is None:
            return

        path = Path(cls.REPORT_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)

        lines = [
            f"# {cls.REPORT_TITLE}",
            "",
            f"Last rewritten: {timezone.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            "",
            cls.REPORT_SCOPE,
            "",
            "This file is rewritten whenever the suite runs.",
        ]

        if summary:
            lines.extend(["", "## Suite Summary", "- Status: completed in the test runner"])

        if cls.REPORT_CASES:
            for case in cls.REPORT_CASES:
                lines.extend(
                    [
                        "",
                        f"## {case['name']}",
                        f"Goal: {case['goal']}",
                        f"Expected: {case['expected']}",
                        f"Observed: {case['observed']}",
                        f"Setup: {case['setup']}",
                        f"Assumptions: {case['assumptions']}",
                        "Output:",
                    ]
                )
                for line in case.get("output", []):
                    lines.append(f"- {line}")
                if case.get("notes"):
                    lines.extend(["Notes:", case["notes"]])

        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")

    def _record_case(self, **case):
        self.__class__.REPORT_CASES.append(case)
        self.__class__._write_report()

    def _log(self, message):
        print(f"[{self.__class__.__name__}.{self._testMethodName}] {message}")
