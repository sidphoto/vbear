"""v0.12 task 8: the "first time you open VBear" page keeps one thing on the server, a yes/no in the config."""

from __future__ import annotations

import unittest

from tests.test_runtimed_s3 import ServerCase


class WelcomeMarkTests(ServerCase):
    def conf(self):
        return self.req("GET", "/api/config")[1]["config"]

    def test_the_mark_starts_false(self):
        self.assertIs(self.conf()["welcome_seen"], False)

    def test_the_mark_is_written_through_the_config_and_must_be_a_real_boolean(self):
        for bad in ("yes", 1, None, [], {}):
            st, r = self.req("POST", "/api/config", {"welcome_seen": bad})
            self.assertEqual(st, 400, (bad, r))
            self.assertIs(self.conf()["welcome_seen"], False)
        st, r = self.req("POST", "/api/config", {"welcome_seen": True})
        self.assertEqual(st, 200, r)
        self.assertIs(self.conf()["welcome_seen"], True)
        st, r = self.req("POST", "/api/config", {"welcome_seen": False})
        self.assertEqual(st, 200, r)
        self.assertIs(self.conf()["welcome_seen"], False)


if __name__ == "__main__":
    unittest.main()
