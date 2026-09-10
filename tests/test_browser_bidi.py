import unittest
from unittest import mock

from tests.browser._bidi import BidiError, FirefoxBidi


class FirefoxBidiNavigationTests(unittest.TestCase):
    def setUp(self):
        self.client = FirefoxBidi(mock.Mock())
        self.client.context = "test-context"

    def test_navigation_uses_non_blocking_acknowledgement_then_waits_for_document(self):
        with mock.patch.object(self.client, "evaluate") as evaluate, mock.patch.object(
            self.client, "command", return_value={}
        ) as command, mock.patch.object(
            self.client, "wait_for_page_ready"
        ) as wait_for_page_ready:
            evaluate.side_effect = ["about:blank", True]
            self.client.navigate("http://127.0.0.1:9001/settings")

        self.assertEqual("location.href", evaluate.call_args_list[0].args[0])
        self.assertIn(
            "window.__dlmsBidiNavigationMarker",
            evaluate.call_args_list[1].args[0],
        )
        command.assert_called_once_with(
            "browsingContext.navigate",
            {
                "context": "test-context",
                "url": "http://127.0.0.1:9001/settings",
                "wait": "none",
            },
            timeout=12.0,
        )
        wait_for_page_ready.assert_called_once()
        readiness_expression = wait_for_page_ready.call_args.args[0]
        self.assertIn("window.__dlmsBidiNavigationMarker", readiness_expression)
        self.assertIn("current.origin === target.origin", readiness_expression)
        self.assertEqual(12.0, wait_for_page_ready.call_args.kwargs["timeout"])

    def test_page_readiness_requires_complete_document_and_specific_condition(self):
        with mock.patch.object(self.client, "wait_for") as wait_for:
            self.client.wait_for_page_ready(
                "location.pathname === '/pdf-import/review/draft' && "
                "document.querySelectorAll('.pdf-import-question-card').length === 2",
                timeout=25,
            )

        expression = wait_for.call_args.args[0]
        self.assertIn("document.readyState === 'complete'", expression)
        self.assertIn("location.pathname === '/pdf-import/review/draft'", expression)
        self.assertIn(".pdf-import-question-card", expression)
        self.assertEqual(25, wait_for.call_args.kwargs["timeout"])

    def test_navigation_does_not_retry_protocol_errors(self):
        with mock.patch.object(
            self.client, "evaluate", side_effect=["about:blank", True]
        ), mock.patch.object(
            self.client, "command", side_effect=BidiError("navigation rejected")
        ) as command:
            with self.assertRaisesRegex(BidiError, "navigation rejected"):
                self.client.navigate("http://127.0.0.1:9001/broken")

        command.assert_called_once()


if __name__ == "__main__":
    unittest.main()
