"""Fail-closed CLI version probes use synthetic executables only."""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sidconsole.runtime import cli_versions as versions


class MinimumPythonTests(unittest.TestCase):
    def test_entry_point_refuses_python_without_macos_waitid(self):
        from sidconsole.__main__ import python_too_old
        self.assertIsNone(python_too_old((3, 13, 0)))
        self.assertIsNone(python_too_old((3, 14, 6)))
        msg = python_too_old((3, 12, 13))
        self.assertIn("3.13", msg)
        self.assertIn("3.12", msg)


class CliVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="sid-cli-version-", dir="/tmp"))
        self.cwd = self.tmp / "workspace"
        self.cwd.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def make_cli(self, engine="codex", body=None, *, executable=True):
        path = self.tmp / engine
        default = (
            'import os,sys\n'
            'print("codex-cli 0.159.2" if sys.argv[1:] == ["--version"] else "bad")\n'
            if engine == "codex" else
            'import os,sys\n'
            'print("2.1.286 (Claude Code)" if sys.argv[1:] == ["--safe-mode", "--version"] else "bad")\n'
        )
        path.write_text(f"#!{sys.executable}\n" + (default if body is None else body), encoding="utf-8")
        path.chmod(0o700 if executable else 0o600)
        return path

    def test_both_trusted_baselines_pass_with_fixed_argv(self):
        self.assertEqual(dict(versions.EXPECTED_VERSIONS), {"codex": "0.159.2", "claude": "2.1.286"})
        for engine in ("codex", "claude"):
            with self.subTest(engine=engine):
                record = self.tmp / f"{engine}-argv.json"
                version = "codex-cli 0.159.2" if engine == "codex" else "2.1.286 (Claude Code)"
                expected_argv = ["--version"] if engine == "codex" else ["--safe-mode", "--version"]
                body = (
                    "import json,os,sys\n"
                    f"open({str(record)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
                    f"print({version!r})\n"
                )
                binary = self.make_cli(engine, body)
                result = versions.check_cli_version(engine, binary, cwd=self.cwd)
                self.assertTrue(result.compatible, result.as_dict())
                self.assertEqual(result.observed_version, versions.EXPECTED_VERSIONS[engine])
                self.assertEqual(result.binary_path, str(binary.resolve()))
                self.assertEqual(result.state, "compatible")
                self.assertEqual(json.loads(record.read_text()), expected_argv)

    def test_path_lookup_uses_the_native_safe_path(self):
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        binary = bin_dir / "codex"
        binary.write_text(
            f"#!{sys.executable}\nprint('codex-cli 0.159.2')\n", encoding="utf-8")
        binary.chmod(0o700)
        with mock.patch.dict(os.environ, {"PATH": str(bin_dir)}):
            result = versions.check_cli_version("codex", cwd=self.cwd)
        self.assertTrue(result.compatible, result.as_dict())
        self.assertEqual(result.binary_path, str(binary.resolve()))

    def test_probe_environment_excludes_caller_integrations(self):
        record = self.tmp / "env.json"
        body = (
            "import json,os,sys\n"
            f"open({str(record)!r}, 'w').write(json.dumps(dict(os.environ)))\n"
            "print('codex-cli 0.159.2')\n"
        )
        binary = self.make_cli("codex", body)
        real_popen = versions.subprocess.Popen
        passed_env = {}

        def capture_popen(*args, **kwargs):
            passed_env.update(kwargs.get("env") or {})
            return real_popen(*args, **kwargs)

        caller_env = {"ORCA_PRIVATE": "do-not-forward", "HERDR_PRIVATE": "do-not-forward"}
        with mock.patch.dict(os.environ, caller_env):
            with mock.patch.object(versions.subprocess, "Popen", side_effect=capture_popen):
                result = versions.check_cli_version("codex", binary, cwd=self.cwd)
        self.assertTrue(result.compatible, result.as_dict())
        self.assertEqual(set(passed_env), {"USER", "LOGNAME", "PATH", "TERM", "LANG", "HOME"})
        child_env = json.loads(record.read_text())
        self.assertNotIn("ORCA_PRIVATE", child_env)
        self.assertNotIn("HERDR_PRIVATE", child_env)

    def test_wrong_version_is_structured_and_fail_closed(self):
        binary = self.make_cli("codex", 'print("codex-cli 0.159.3")\n')
        result = versions.check_cli_version("codex", binary, cwd=self.cwd)
        self.assertFalse(result.compatible)
        self.assertEqual(result.error_code, "version_mismatch")
        self.assertEqual(result.observed_version, "0.159.3")
        with self.assertRaises(versions.VersionAssertionError) as caught:
            versions.assert_cli_version("codex", binary, cwd=self.cwd)
        self.assertEqual(caught.exception.code, "version_mismatch")
        self.assertEqual(caught.exception.result.as_dict()["expected_version"], "0.159.2")

        claude = self.make_cli("claude", 'print("2.1.287 (Claude Code)")\n')
        result = versions.check_cli_version("claude", claude, cwd=self.cwd)
        self.assertEqual(result.error_code, "version_mismatch")
        self.assertEqual(result.observed_version, "2.1.287")

    def test_missing_and_non_executable_binaries_fail_closed(self):
        missing = versions.check_cli_version("codex", self.tmp / "missing-codex", cwd=self.cwd)
        self.assertEqual(missing.error_code, "binary_not_found")
        nonexec = self.make_cli("codex", executable=False)
        result = versions.check_cli_version("codex", nonexec, cwd=self.cwd)
        self.assertEqual(result.error_code, "binary_not_executable")

    def test_timeout_nonzero_and_output_limit_fail_closed(self):
        slow = self.make_cli("codex", "import time\ntime.sleep(10)\n")
        result = versions.check_cli_version("codex", slow, cwd=self.cwd, timeout=0.1)
        self.assertEqual(result.error_code, "probe_timeout")

        stopped = self.tmp / "child-stopped"
        ready = self.tmp / "child-ready"
        child_script = self.tmp / "probe-child.py"
        child_script.write_text(
            "import signal,sys,time\n"
            f"def stop(*_):\n open({str(stopped)!r}, 'w').write('stopped')\n sys.exit(0)\n"
            "signal.signal(signal.SIGTERM, stop)\n"
            f"open({str(ready)!r}, 'w').close()\n"
            "time.sleep(30)\n",
            encoding="utf-8",
        )
        child_body = (
            "import os,subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable, {str(child_script)!r}])\n"
            "deadline=time.monotonic()+1.5\n"
            f"while not os.path.exists({str(ready)!r}) and time.monotonic()<deadline:\n"
            " time.sleep(0.01)\n"
            "print('codex-cli 0.159.2')\n"
        )
        with_child = self.make_cli("codex", child_body)
        result = versions.check_cli_version("codex", with_child, cwd=self.cwd, timeout=2.0)
        self.assertEqual(result.error_code, "probe_timeout")
        self.assertTrue(stopped.exists(), "timeout cleanup should signal the probe process group")

        nonzero = self.make_cli("codex", 'print("codex-cli 0.159.2")\nraise SystemExit(7)\n')
        result = versions.check_cli_version("codex", nonzero, cwd=self.cwd)
        self.assertEqual(result.error_code, "probe_failed")

        large = self.make_cli("codex", 'print("x" * 5000)\n')
        result = versions.check_cli_version("codex", large, cwd=self.cwd)
        self.assertEqual(result.error_code, "output_too_large")

        large_stderr = self.make_cli("codex", 'import sys\nsys.stderr.write("x" * 5000)\n')
        result = versions.check_cli_version("codex", large_stderr, cwd=self.cwd)
        self.assertEqual(result.error_code, "output_too_large")

    def test_invalid_utf8_multiline_junk_and_fake_versions_fail_closed(self):
        cases = [
            ("invalid_utf8", "import os\nos.write(1, b'codex-cli \\xff')\n"),
            ("invalid_output", 'print("codex-cli 0.159.2\\nextra")\n'),
            ("invalid_output", 'print("codex-cli 0.159.2 forged")\n'),
            ("invalid_output", 'print("version 0.159.2")\n'),
        ]
        for index, (code, body) in enumerate(cases):
            with self.subTest(body=body):
                binary = self.make_cli("codex", body)
                result = versions.check_cli_version("codex", binary, cwd=self.cwd)
                self.assertEqual(result.error_code, code)

    def test_shared_unknown_and_client_baseline_override_are_rejected(self):
        shared = versions.check_cli_version("shared", cwd=self.cwd)
        self.assertEqual(shared.error_code, "unsupported_engine")
        invalid = versions.check_cli_version([], cwd=self.cwd)
        self.assertEqual(invalid.error_code, "unsupported_engine")
        with self.assertRaises(TypeError):
            versions.check_cli_version("codex", cwd=self.cwd, expected_version="9.9.9")

    def test_file_replacement_after_probe_is_rejected_before_launch(self):
        binary = self.make_cli("codex")
        result = versions.assert_cli_version("codex", binary, cwd=self.cwd)
        replacement = self.tmp / "replacement"
        replacement.write_text(f"#!{sys.executable}\nprint('codex-cli 0.159.2')\n", encoding="utf-8")
        replacement.chmod(0o700)
        os.replace(replacement, binary)
        with self.assertRaises(versions.VersionAssertionError) as caught:
            versions.ensure_binary_unchanged(result)
        self.assertEqual(caught.exception.code, "binary_changed_before_launch")


if __name__ == "__main__":
    unittest.main()
