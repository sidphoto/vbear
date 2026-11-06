"""Packaging copies of VBear.app must not show up in Spotlight or Launchpad (issue #27).

macOS skips a folder whose name ends in ".noindex", so every .app that macos/build.sh leaves behind sits in one.
These tests only read macos/build.sh, the release workflow and the docs; build.sh is never run.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_SH = (ROOT / "macos" / "build.sh").read_text(encoding="utf-8")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")


def code_lines(text):
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("#")]


def shell_vars(text):
    """Simple NAME="value" assignments of the script, with $NAME / ${NAME} expanded from earlier ones."""
    values = {"ROOT": "<root>"}
    for line in code_lines(text):
        m = re.match(r'^([A-Z_]+)="([^"]*)"$', line)
        if m and "$(" not in m.group(2):
            values[m.group(1)] = expand(m.group(2), values)
    return values


def expand(value, values):
    return re.sub(r"\$\{?([A-Z_]+)\}?", lambda m: values.get(m.group(1), m.group(0)), value)


VARS = shell_vars(BUILD_SH)


def app_parent(path):
    """The folder that holds a '.../VBear.app' path, or None for other paths."""
    m = re.search(r"([^/]+)/VBear\.app(?:/|$)", path)
    return m.group(1) if m else None


class BuildScriptKeepsAppsOutOfSpotlight(unittest.TestCase):
    def test_the_working_bundle_lives_in_a_noindex_folder(self):
        self.assertEqual(VARS["APP"], "<root>/build/app.noindex/VBear.app")

    def test_every_ditto_target_that_is_an_app_sits_in_a_noindex_folder(self):
        targets = []
        for line in code_lines(BUILD_SH):
            m = re.match(r'^ditto\s+"[^"]+"\s+"([^"]+)"', line)
            if m:
                targets.append(expand(m.group(1), VARS))
        apps = [t for t in targets if t.endswith(".app")]
        self.assertEqual(len(apps), 2, targets)  # the disk image stage and dist/
        for target in apps:
            self.assertTrue(app_parent(target).endswith(".noindex"), target)

    def test_the_finished_copy_in_dist_is_in_a_noindex_folder(self):
        dist_copy = [expand(m.group(1), VARS) for m in re.finditer(r'ditto "\$APP" "([^"]*\$DIST[^"]*)"', BUILD_SH)]
        self.assertEqual(dist_copy, ["<root>/dist/app.noindex/VBear.app"])

    def test_no_executable_line_names_a_bundle_outside_a_noindex_folder(self):
        for line in code_lines(BUILD_SH):
            if line.startswith("rm -rf") and "<root>/build/VBear.app" in expand(line, VARS):
                continue  # the removal of the old places, checked in its own test
            for token in re.findall(r'"([^"]*VBear\.app[^"]*)"', expand(line, VARS)):
                if token == "/Applications/VBear.app":
                    # only the path recorded inside the byte-compiled files (compileall -p), nothing is written there
                    self.assertTrue(line.startswith('-s "$APP" -p '), line)
                    continue
                self.assertTrue((app_parent(token) or "").endswith(".noindex"), line)

    def test_nothing_is_installed_into_applications(self):
        for line in code_lines(BUILD_SH):
            if "/Applications" in line:
                self.assertTrue(line.startswith(('-s "$APP" -p ', "ln -s /Applications ")), line)

    def test_the_disk_image_is_staged_in_a_noindex_folder_and_keeps_its_content_and_name(self):
        self.assertEqual(VARS["STAGE"], "<root>/build/dmg.noindex")
        self.assertIn('ditto "$APP" "$STAGE/VBear.app"', BUILD_SH)       # inside the image: VBear.app
        self.assertIn('ln -s /Applications "$STAGE/Applications"', BUILD_SH)  # and the Applications shortcut
        self.assertIn('hdiutil create -quiet -volname "VBear $VERSION" -srcfolder "$STAGE"', BUILD_SH)
        self.assertEqual(VARS["DMG"], "<root>/dist/VBear-$VERSION-arm64.dmg")
        self.assertIn('shasum -a 256 "$DMG" | tee "$DMG.sha256"', BUILD_SH)

    def test_only_old_copies_inside_the_repository_are_removed_before_the_build_starts(self):
        lines = code_lines(BUILD_SH)
        legacy = [i for i, line in enumerate(lines) if line.startswith("rm -rf") and "VBear.app" in line
                  or line.startswith("rm -rf") and line.endswith('"$BUILD/dmg"')]
        first_step = next(i for i, line in enumerate(lines) if line.startswith('mkdir -p "$CACHE"'))
        removed = set()
        for i in legacy:
            if i < first_step:
                removed.update(expand(p, VARS) for p in re.findall(r'"([^"]+)"', lines[i]))
        self.assertEqual(removed, {"<root>/build/VBear.app", "<root>/build/dmg", "<root>/dist/VBear.app"})
        # the old removals in the DMG step are gone: they would point at the old places
        self.assertNotIn('rm -rf "$STAGE" "$DIST/VBear.app"', BUILD_SH)

    def test_the_header_names_the_new_output_path(self):
        self.assertIn("dist/app.noindex/VBear.app", BUILD_SH.splitlines()[1])


class ReleaseWorkflowReadsTheSamePaths(unittest.TestCase):
    def smoke_step(self):
        return RELEASE[RELEASE.index("Smoke-check the bundle"):RELEASE.index("Publish to the release")]

    def test_smoke_check_reads_the_app_build_sh_writes_to_dist(self):
        m = re.search(r"^\s*app=(\S+)\s*$", self.smoke_step(), re.M)
        self.assertIsNotNone(m)
        self.assertEqual("<root>/" + m.group(1), "<root>/dist/app.noindex/VBear.app")
        self.assertEqual("<root>/" + m.group(1), expand('$DIST/app.noindex/VBear.app', VARS))
        self.assertIn(f'ditto "$APP" "$DIST/app.noindex/VBear.app"', BUILD_SH)

    def test_the_old_dist_path_is_not_used_anywhere(self):
        self.assertNotIn("dist/VBear.app", RELEASE)

    def test_upload_still_takes_the_dmg_and_its_checksum_from_dist(self):
        self.assertIn('gh release upload "$TAG" dist/VBear-*-arm64.dmg dist/VBear-*-arm64.dmg.sha256 --clobber', RELEASE)


class DocsNameTheNewPaths(unittest.TestCase):
    def test_architecture_says_where_the_apps_go_and_why(self):
        text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
        self.assertIn("dist/app.noindex/VBear.app", text)
        self.assertIn("Spotlight", text)
        self.assertIn("Launchpad", text)


if __name__ == "__main__":
    unittest.main()
