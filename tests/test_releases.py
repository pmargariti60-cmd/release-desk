from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier
import unittest

from releases import Store, WorkflowError


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "test.sqlite3"
        self.store = Store(self.path)
        self.draft = self.store.create({
            "title": "Calendar improvements",
            "project": "Harbor Studio",
            "body": "Clients can reschedule appointments.",
        })

    def change(self, action, version, **fields):
        return self.store.change(self.draft["id"], {"action": action, "version": version, **fields})

    def test_review_feedback_approval_and_reopen(self):
        with self.assertRaises(WorkflowError):
            self.store.export(self.draft["id"])
        self.change("submit", 1)
        with self.assertRaises(WorkflowError):
            self.change("return", 2)
        self.change("return", 2, note="Say when the update is available.")
        self.change("edit", 3, title="Reschedule online", project="Harbor Studio",
                    body="Online rescheduling is available today.")
        self.change("submit", 4)
        self.change("approve", 5)
        self.assertEqual(
            Store(self.path).export(self.draft["id"]),
            "# Reschedule online\n\nHarbor Studio\n\nOnline rescheduling is available today.\n",
        )
        self.change("reopen", 6, note="Update rollout timing.")
        with self.assertRaises(WorkflowError):
            self.store.export(self.draft["id"])
        history = self.store.get(self.draft["id"])["history"]
        self.assertEqual(
            [event["action"] for event in history],
            ["reopen", "approve", "submit", "edit", "return", "submit", "created"],
        )
        self.assertEqual(history[4]["note"], "Say when the update is available.")

    def test_concurrent_review_decisions_commit_once(self):
        self.change("submit", 1)
        start = Barrier(2)

        def decide(action):
            start.wait(timeout=5)
            try:
                self.change(action, 2, note="Add context.")
                return 200
            except WorkflowError as error:
                return error.status

        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(decide, ["approve", "return"]))
        self.assertEqual(sorted(result), [200, 409])
        current = self.store.get(self.draft["id"])
        self.assertEqual(current["version"], 3)
        self.assertEqual(len(current["history"]), 3)
