"""Internal NativeRuntime Agent version gate; fake CLIs only, no model launch."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from vbear.runtime import cli_versions
from vbear.runtime.native import NativeRuntime, NativeRuntimeError


class NativeAgentVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sid-native-agent-version-", dir="/tmp"))
        self.cwd = self.tmp / "workspace"
        self.cwd.mkdir()
        self.binary = self.tmp / "codex"
        self.binary.write_text(
            f"#!{sys.executable}\nprint('codex-cli 0.159.2')\n", encoding="utf-8")
        self.binary.chmod(0o700)
        self.runtime = NativeRuntime(self.tmp / "state", autostart=True)
        self.rpc = mock.Mock(return_value={
            "ok": True,
            "result": {"session_id": "n-0123456789ab", "argv": []},
        })
        self.runtime._rpc = self.rpc
        self.ensure_daemon = mock.Mock(return_value=False)
        self.runtime.ensure_daemon = self.ensure_daemon

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def spec(self, *, argv=None, **extra):
        value = {"argv": [str(self.binary), "--help"] if argv is None else argv,
                 "cwd": str(self.cwd)}
        value.update(extra)
        return value

    def test_success_asserts_before_one_open_and_pins_same_binary(self):
        result = self.runtime.create_checked_agent_session("codex", self.spec())
        self.rpc.assert_called_once()
        args, kwargs = self.rpc.call_args
        self.assertEqual(args, ("open",))
        self.assertEqual(kwargs["argv"], [str(self.binary.resolve()), "--help"])
        self.assertEqual(kwargs["cwd"], str(self.cwd.resolve()))
        self.assertNotIn("env", kwargs)
        self.assertEqual(result["state"], "version_checked_unmanaged")
        self.assertTrue(result["version_assertion"]["compatible"])
        self.ensure_daemon.assert_not_called()

    def test_wrong_version_never_opens_or_ensures_daemon(self):
        self.binary.write_text(
            f"#!{sys.executable}\nprint('codex-cli 0.159.3')\n", encoding="utf-8")
        self.binary.chmod(0o700)
        with self.assertRaises(cli_versions.VersionAssertionError) as caught:
            self.runtime.create_checked_agent_session("codex", self.spec())
        self.assertEqual(caught.exception.code, "version_mismatch")
        self.rpc.assert_not_called()
        self.ensure_daemon.assert_not_called()

    def test_unsupported_engine_and_mismatched_argv_are_rejected(self):
        with self.assertRaises(cli_versions.VersionAssertionError) as caught:
            self.runtime.create_checked_agent_session("shared", self.spec(argv=["/bin/sh"]))
        self.assertEqual(caught.exception.code, "unsupported_engine")
        with self.assertRaises(NativeRuntimeError):
            self.runtime.create_checked_agent_session("codex", self.spec(argv=["/bin/sh", "-c", "true"]))
        self.rpc.assert_not_called()
        self.ensure_daemon.assert_not_called()

    def test_extra_env_or_unknown_spec_fields_are_rejected(self):
        with self.assertRaises(NativeRuntimeError):
            self.runtime.create_checked_agent_session("codex", self.spec(env={"PATH": "/tmp"}))
        with self.assertRaises(NativeRuntimeError):
            self.runtime.create_checked_agent_session("codex", self.spec(shell=True))
        self.rpc.assert_not_called()

    def test_invalid_dimensions_are_rejected_before_version_check_or_daemon(self):
        invalid_dimensions = (
            ("cols", "invalid"), ("cols", True), ("cols", 0), ("cols", 1001),
            ("rows", -1), ("rows", False), ("rows", 1.5), ("rows", 1001),
        )
        with mock.patch.object(cli_versions, "assert_cli_version") as version_assertion:
            for dimension, value in invalid_dimensions:
                with self.subTest(dimension=dimension, value=value):
                    with self.assertRaises(NativeRuntimeError):
                        self.runtime.create_checked_agent_session(
                            "codex", self.spec(**{dimension: value}))
        version_assertion.assert_not_called()
        self.rpc.assert_not_called()
        self.ensure_daemon.assert_not_called()

    def test_nul_cwd_is_rejected_before_version_check_or_daemon(self):
        with mock.patch.object(cli_versions, "assert_cli_version") as version_assertion:
            with self.assertRaises(NativeRuntimeError):
                self.runtime.create_checked_agent_session("codex", self.spec(cwd="/tmp/\0bad"))
        version_assertion.assert_not_called()
        self.rpc.assert_not_called()
        self.ensure_daemon.assert_not_called()

    def test_binary_replacement_between_probe_and_open_fails_closed(self):
        original_assert = cli_versions.assert_cli_version

        def assert_then_replace(engine, binary, *, cwd):
            result = original_assert(engine, binary, cwd=cwd)
            replacement = self.tmp / "replacement"
            replacement.write_text(
                f"#!{sys.executable}\nprint('codex-cli 0.159.2')\n", encoding="utf-8")
            replacement.chmod(0o700)
            os.replace(replacement, self.binary)
            return result

        with mock.patch.object(cli_versions, "assert_cli_version", side_effect=assert_then_replace):
            with self.assertRaises(cli_versions.VersionAssertionError) as caught:
                self.runtime.create_checked_agent_session("codex", self.spec())
        self.assertEqual(caught.exception.code, "binary_changed_before_launch")
        self.rpc.assert_not_called()
        self.ensure_daemon.assert_not_called()

    def test_general_shell_create_session_remains_unguarded(self):
        with mock.patch.object(cli_versions, "assert_cli_version") as assertion:
            self.runtime.create_session({
                "argv": ["/bin/sh", "-c", "echo unchanged"],
                "cwd": str(self.cwd),
            })
        assertion.assert_not_called()
        self.rpc.assert_called_once_with(
            "open", timeout=5.0,
            argv=["/bin/sh", "-c", "echo unchanged"], cwd=str(self.cwd))


if __name__ == "__main__":
    unittest.main()
