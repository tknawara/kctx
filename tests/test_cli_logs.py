"""Log commands retain event order and report empty selections as partial."""

import io
import json
from contextlib import redirect_stdout
from unittest import TestCase
from unittest.mock import patch

from kctx.cli.app import main


class LogsCommandTest(TestCase):
    def invoke(self, *args):
        output = io.StringIO()
        with redirect_stdout(output):
            code = main(["--json", "logs", *args])
        return code, json.loads(output.getvalue())

    def test_selects_run_and_last_events(self):
        events = [{"event": "first"}, {"event": "second"}, {"event": "third"}]
        with patch("kctx.cli.logs.read_events", return_value=events) as read:
            code, payload = self.invoke("--run", "chosen", "--last", "2")
        read.assert_called_once_with(run_id="chosen")
        self.assertEqual((code, payload), (0, events[-2:]))

    def test_empty_events_are_partial(self):
        with patch("kctx.cli.logs.read_events", return_value=[]):
            self.assertEqual(self.invoke(), (2, []))
