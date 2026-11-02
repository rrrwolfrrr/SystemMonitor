"""Checks that importing the server does not start background services."""

import unittest


class LifecycleTests(unittest.TestCase):
    def test_import_has_no_running_threads(self):
        import server_core

        self.assertIsNone(server_core.ws_thread)
        self.assertIsNone(server_core.updater_thread)

