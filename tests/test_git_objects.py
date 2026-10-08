"""commit_exists (vbear/git_objects.py, design 5.7) against repositories made
by git in the test. git is a development tool here; VBear never runs it."""

import os
import random
import shutil
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from vbear import git_objects as go
from vbear.git_objects import commit_exists

GIT = shutil.which("git")
ENV = {**os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
       "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
       "GIT_COMMITTER_EMAIL": "t@t"}


def git(cwd, *args) -> str:
    return subprocess.run([GIT, *args], cwd=cwd, env=ENV, capture_output=True, text=True,
                          check=True).stdout.strip()


def build(path: Path, fmt: str, commits: int = 30) -> list[str]:
    path.mkdir()
    git(path, "init", "-q", f"--object-format={fmt}")
    shas = []
    for i in range(commits):
        (path / "f").write_text(f"line {i}\n" * 50)
        git(path, "add", "f")
        git(path, "commit", "-q", "-m", f"long message {i} " + "x" * 3000)
        shas.append(git(path, "rev-parse", "HEAD"))
    git(path, "tag", "-a", "v1", "-m", "an annotated tag")
    return shas


def pack(path: Path, *extra):
    git(path, *extra, "repack", "-q", "-a", "-d", "-f", "--depth=50", "--window=50")
    git(path, "prune-packed")


def pack_files(path: Path) -> tuple[Path, Path]:
    d = path / ".git" / "objects" / "pack"
    idx = next(d.glob("pack-*.idx"))
    return idx, idx.with_suffix(".pack")


def commit_depths(path: Path) -> dict[str, int]:
    idx, _ = pack_files(path)
    out = git(path, "verify-pack", "-v", str(idx))
    depths = {}
    for line in out.splitlines():
        bits = line.split()
        if len(bits) >= 5 and bits[1] == "commit":
            depths[bits[0]] = int(bits[5]) if len(bits) >= 7 else 0
    return depths


def flip(path: Path, pos: int):
    data = bytearray(path.read_bytes())
    data[pos] ^= 0xFF
    path.chmod(0o644)
    path.write_bytes(bytes(data))


@unittest.skipUnless(GIT, "git is needed to build test repositories")
class GitObjectsCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbgo-")))
        cls.loose = {}
        for fmt in ("sha1", "sha256"):
            cls.loose[fmt] = (cls.tmp / f"loose-{fmt}", build(cls.tmp / f"loose-{fmt}", fmt))
        cls.packed = {}
        for fmt in ("sha1", "sha256"):
            src, shas = cls.loose[fmt]
            dst = cls.tmp / f"packed-{fmt}"
            shutil.copytree(src, dst, symlinks=True)
            pack(dst)
            cls.packed[fmt] = (dst, shas)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def setUp(self):
        go._checksum_cache.clear()

    def copy(self, src: Path) -> Path:
        dst = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbgo-case-"))) / "repo"
        self.addCleanup(shutil.rmtree, dst.parent, True)
        shutil.copytree(src, dst, symlinks=True)
        return dst


class BasicTests(GitObjectsCase):
    def test_loose_objects_in_both_formats(self):
        for fmt in ("sha1", "sha256"):
            with self.subTest(fmt=fmt):
                repo, shas = self.loose[fmt]
                self.assertIs(commit_exists(str(repo), shas[0]), True)
                self.assertIs(commit_exists(str(repo), shas[-1]), True)
                self.assertIs(commit_exists(str(repo), git(repo, "rev-parse", "HEAD:f")), False)       # blob
                self.assertIs(commit_exists(str(repo), git(repo, "rev-parse", "HEAD^{tree}")), False)  # tree
                self.assertIs(commit_exists(str(repo), git(repo, "rev-parse", "v1")), False)           # tag
                self.assertIs(commit_exists(str(repo), "0" * len(shas[0])), False)                     # absent

    def test_packed_objects_and_delta_chains_in_both_formats(self):
        for fmt in ("sha1", "sha256"):
            with self.subTest(fmt=fmt):
                repo, shas = self.packed[fmt]
                self.assertFalse(list((repo / ".git" / "objects").glob("??/*")), "objects should be packed")
                depths = commit_depths(repo)
                deltas = [s for s, d in depths.items() if d > 0]
                self.assertTrue(deltas, "the test needs a commit stored as a delta")
                for sha in shas + deltas:
                    self.assertIs(commit_exists(str(repo), sha), True, sha)
                self.assertIs(commit_exists(str(repo), git(repo, "rev-parse", "HEAD:f")), False)
                self.assertIs(commit_exists(str(repo), "f" * len(shas[0])), False)

    def test_ref_deltas(self):
        repo = self.copy(self.loose["sha1"][0])
        pack(repo, "-c", "repack.useDeltaBaseOffset=false")
        idx, packfile = pack_files(repo)
        chk = go._Check("sha1")
        try:
            objects = chk.open_path(str(repo / ".git" / "objects"))[-1][1]
            p = go._Pack(chk, chk.open_dir("pack", objects), idx.name)
            kinds = set()
            for sha in commit_depths(repo):
                kinds.add(go._varint_size(chk, p.pack, p.find(bytes.fromhex(sha)))[0])
        finally:
            chk.close()
        self.assertIn(go._REF_DELTA, kinds, "the test needs a commit stored as a ref delta")
        for sha in commit_depths(repo):
            self.assertIs(commit_exists(str(repo), sha), True)

    def test_large_offset_table(self):
        repo = self.copy(self.packed["sha1"][0])
        idx, packfile = pack_files(repo)
        idx.unlink()
        git(repo, "index-pack", "--index-version=2,0", "-o", str(idx), str(packfile))
        size = idx.stat().st_size
        n = int.from_bytes(idx.read_bytes()[8 + 255 * 4:8 + 256 * 4], "big")
        self.assertGreater(size, 8 + 1024 + n * 28 + 40, "the test needs 64-bit offsets")
        for sha in self.packed["sha1"][1]:
            self.assertIs(commit_exists(str(repo), sha), True)

    def test_worktrees_absolute_and_relative(self):
        repo = self.copy(self.loose["sha1"][0])
        shas = self.loose["sha1"][1]
        git(repo, "worktree", "add", "-q", "--detach", str(repo.parent / "wt-abs"), shas[3])
        git(repo, "worktree", "add", "-q", "--relative-paths", "--detach", str(repo.parent / "wt-rel"), shas[4])
        self.assertTrue((repo.parent / "wt-rel" / ".git").read_text().startswith("gitdir: .."))
        for wt in ("wt-abs", "wt-rel"):
            with self.subTest(wt=wt):
                self.assertIs(commit_exists(str(repo.parent / wt), shas[0]), True)
                self.assertIs(commit_exists(str(repo.parent / wt / "sub-does-not-exist"), shas[0]), None)

    def test_inside_a_subdirectory_of_the_worktree(self):
        repo = self.copy(self.loose["sha1"][0])
        (repo / "a" / "b").mkdir(parents=True)
        self.assertIs(commit_exists(str(repo / "a" / "b"), self.loose["sha1"][1][0]), True)


class FailClosedTests(GitObjectsCase):
    def test_not_a_repository_or_the_home_directory(self):
        plain = Path(os.path.realpath(tempfile.mkdtemp(prefix="vbgo-plain-")))
        self.addCleanup(shutil.rmtree, plain, True)
        self.assertIsNone(commit_exists(str(plain), "a" * 40))
        repo, shas = self.loose["sha1"]
        with mock.patch.dict(os.environ, {"HOME": str(repo)}):
            self.assertIsNone(commit_exists(str(repo), shas[0]))      # home is never a project

    def test_symlinks_anywhere_give_none(self):
        repo = self.copy(self.packed["sha1"][0])
        sha = self.packed["sha1"][1][0]
        link = repo.parent / "link"
        link.symlink_to(repo)
        self.assertIsNone(commit_exists(str(link), sha))                       # the work directory path
        objects = repo / ".git" / "objects"
        moved = repo.parent / "objects-real"
        objects.rename(moved)
        objects.symlink_to(moved)
        self.assertIsNone(commit_exists(str(repo), sha))                       # objects/
        objects.unlink()
        moved.rename(objects)
        self.assertIs(commit_exists(str(repo), sha), True)
        idx, _ = pack_files(repo)
        real = repo.parent / "real.idx"
        idx.rename(real)
        idx.symlink_to(real)
        self.assertIsNone(commit_exists(str(repo), sha))                       # a pack index

    def test_dot_git_symlink_and_broken_dot_git_files(self):
        repo = self.copy(self.loose["sha1"][0])
        sha = self.loose["sha1"][1][0]
        other = repo.parent / "w"
        other.mkdir()
        (other / ".git").symlink_to(repo / ".git")
        self.assertIsNone(commit_exists(str(other), sha))
        (other / ".git").unlink()
        for text in ("nonsense", "gitdir:", f"gitdir: {repo.parent / 'missing'}", "gitdir: ../w/../link"):
            with self.subTest(text=text):
                (other / ".git").write_text(text + "\n")
                self.assertIsNone(commit_exists(str(other), sha))
        (other / ".git").write_text(f"gitdir: {repo / '.git'}\n")
        self.assertIs(commit_exists(str(other), sha), True)
        # A component that a textual ".." would have skipped is still opened,
        # and a symlink there gives None.
        (repo.parent / "sym").symlink_to(repo.parent)
        (other / ".git").write_text("gitdir: ../sym/../repo/.git\n")
        self.assertIsNone(commit_exists(str(other), sha))
        (other / ".git").write_text(f"gitdir: {repo.parent}/sym/../repo/.git\n")
        self.assertIsNone(commit_exists(str(other), sha))
        (other / ".git").write_text("gitdir: ../w/../repo/.git\n")
        self.assertIs(commit_exists(str(other), sha), True)

    def test_commondir_through_a_symlink(self):
        repo = self.copy(self.loose["sha1"][0])
        sha = self.loose["sha1"][1][0]
        git(repo, "worktree", "add", "-q", "--detach", str(repo.parent / "wt"), sha)
        gitdir = repo / ".git" / "worktrees" / "wt"
        self.assertEqual((gitdir / "commondir").read_text().strip(), "../..")
        self.assertIs(commit_exists(str(repo.parent / "wt"), sha), True)
        (repo.parent / "alias").symlink_to(repo)
        (gitdir / "commondir").write_text(f"{repo.parent}/alias/.git\n")
        self.assertIsNone(commit_exists(str(repo.parent / "wt"), sha))
        (gitdir / "commondir").write_text(f"{repo}/.git\n")
        self.assertIs(commit_exists(str(repo.parent / "wt"), sha), True)

    def test_loose_subdirectory_symlink(self):
        repo = self.copy(self.loose["sha1"][0])
        sha = self.loose["sha1"][1][0]
        sub = repo / ".git" / "objects" / sha[:2]
        moved = repo.parent / "sub-real"
        sub.rename(moved)
        sub.symlink_to(moved)
        self.assertIsNone(commit_exists(str(repo), sha))

    def test_alternates(self):
        src = self.copy(self.loose["sha1"][0])
        shared = src.parent / "shared"
        git(src.parent, "clone", "-q", "--shared", str(src), str(shared))
        self.assertTrue((shared / ".git" / "objects" / "info" / "alternates").exists())
        self.assertIsNone(commit_exists(str(shared), self.loose["sha1"][1][0]))   # only in the alternate
        (shared / "g").write_text("own\n")
        git(shared, "add", "g")
        git(shared, "commit", "-q", "-m", "own")
        self.assertIs(commit_exists(str(shared), git(shared, "rev-parse", "HEAD")), True)

    def test_forged_and_damaged_loose_objects(self):
        repo, shas = self.loose["sha1"]
        cases = {
            "forged": lambda raw: zlib.compress(zlib.decompress(raw).replace(b"long message", b"LONG MESSAGE")),
            "garbage after the stream": lambda raw: raw + b"trailing",
            "truncated": lambda raw: raw[:len(raw) // 2],
            "not zlib": lambda raw: b"\x00" * 40,
            "bad header": lambda raw: zlib.compress(b"commit x\0" + zlib.decompress(raw).partition(b"\0")[2]),
            "size mismatch": lambda raw: zlib.compress(b"commit 1\0" + zlib.decompress(raw).partition(b"\0")[2]),
        }
        for name, change in cases.items():
            with self.subTest(case=name):
                copy = self.copy(repo)
                path = copy / ".git" / "objects" / shas[0][:2] / shas[0][2:]
                raw = path.read_bytes()
                path.chmod(0o644)
                path.write_bytes(change(raw))
                self.assertIsNone(commit_exists(str(copy), shas[0]))

    def test_damaged_or_truncated_idx_and_pack(self):
        repo, shas = self.packed["sha1"]
        h = 20

        def damage(target, how):
            copy = self.copy(repo)
            idx, packfile = pack_files(copy)
            path = idx if target == "idx" else packfile
            if how == "truncate":
                data = path.read_bytes()
                path.chmod(0o644)
                path.write_bytes(data[:len(data) - 7])
            elif how == "idx-records-other-pack-checksum":
                flip(idx, idx.stat().st_size - 2 * h + 3)
            else:
                flip(path, how)
            return copy

        for target, how in (("idx", "truncate"), ("pack", "truncate"), ("idx", 8 + 1024 + 5),
                            ("idx", 5), ("pack", 100), ("pack", 6), ("idx", "idx-records-other-pack-checksum")):
            with self.subTest(target=target, how=how):
                self.assertIsNone(commit_exists(str(damage(target, how)), shas[0]))

    def test_forged_pack_entry_with_valid_checksums(self):
        # The idx claims sha Y for commit A's data and its checksum is
        # recomputed, so every container check passes: only the object hash
        # can catch it.
        import hashlib
        repo = self.copy(self.packed["sha1"][0])
        idx, _ = pack_files(repo)
        data = bytearray(idx.read_bytes())
        n = int.from_bytes(data[8 + 255 * 4:8 + 256 * 4], "big")
        names = [bytes(data[1032 + i * 20:1032 + (i + 1) * 20]) for i in range(n)]
        commits = set(commit_depths(repo))
        for i, name in enumerate(names):
            forged = name[:-1] + bytes([name[-1] + 1]) if name[-1] < 0xFF else None
            if (name.hex() in commits and forged and (i + 1 == n or forged < names[i + 1])):
                break
        else:
            self.skipTest("no commit entry can be renamed in place")
        data[1032 + i * 20:1032 + (i + 1) * 20] = forged
        data[-20:] = hashlib.sha1(bytes(data[:-20])).digest()
        idx.chmod(0o644)
        idx.write_bytes(bytes(data))
        self.assertIsNone(commit_exists(str(repo), forged.hex()))

    def test_any_single_byte_change_never_passes(self):
        # Damage never yields True. It is usually None (a checksum fails);
        # a flip in the idx name table can instead hide the object, which
        # then reads as not found (False): design 5.7 verifies only the
        # pack/idx pair the object was found in, and both answers block.
        repo, shas = self.packed["sha1"]
        rng = random.Random(8)
        copy = self.copy(repo)
        idx, packfile = pack_files(copy)
        originals = {p: p.read_bytes() for p in (idx, packfile)}
        for p in originals:
            p.chmod(0o644)
        for _ in range(40):
            target = rng.choice([idx, packfile])
            data = bytearray(originals[target])
            data[rng.randrange(len(data))] ^= 1 << rng.randrange(8)
            target.write_bytes(bytes(data))
            for sha in (shas[0], shas[-1]):
                self.assertIn(commit_exists(str(copy), sha), (None, False))
            target.write_bytes(originals[target])

    def test_limits(self):
        repo, shas = self.packed["sha1"]
        depths = commit_depths(repo)
        delta = max(depths, key=depths.get)
        whole = next(s for s, d in depths.items() if d == 0)
        loose_repo, loose_shas = self.loose["sha1"]
        checks = [
            ("DELTA_MAX_DEPTH", depths[delta] - 1, repo, delta),
            ("OBJECT_MAX", 100, repo, whole),
            ("TOTAL_INFLATE_MAX", 100, repo, whole),
            ("OBJECT_MAX_COMPRESSED", 10, repo, whole),
            ("CHECKSUM_PACK_MAX", 100, repo, whole),
            ("IDX_MAX_OBJECTS", 3, repo, whole),
            ("IDX_MAX_BYTES", 100, repo, whole),
            ("PACK_MAX_BYTES", 100, repo, whole),
            ("IDX_MAX_FILES", 0, repo, whole),
            ("PACK_DIR_MAX_ENTRIES", 1, repo, whole),
            ("DEADLINE_S", -1.0, repo, whole),
            ("CHECKSUM_DEADLINE_S", -1.0, repo, whole),
            ("LOOSE_MAX_COMPRESSED", 10, loose_repo, loose_shas[0]),
            ("OBJECT_MAX", 100, loose_repo, loose_shas[0]),
            ("DEADLINE_S", -1.0, loose_repo, loose_shas[0]),
        ]
        self.assertIs(commit_exists(str(repo), delta), True)
        for name, value, where, sha in checks:
            with self.subTest(limit=name):
                go._checksum_cache.clear()
                with mock.patch.object(go, name, value):
                    self.assertIsNone(commit_exists(str(where), sha))
        with mock.patch.object(go, "DELTA_MAX_DEPTH", depths[delta]):
            self.assertIs(commit_exists(str(repo), delta), True)      # the limit itself is allowed

    def test_checksum_cache_follows_the_files(self):
        repo = self.copy(self.packed["sha1"][0])
        sha = self.packed["sha1"][1][0]
        real = go._Pack._digest
        calls = []

        def counted(self_, fd, length, deadline):
            calls.append(length)
            return real(self_, fd, length, deadline)
        with mock.patch.object(go._Pack, "_digest", counted):
            self.assertIs(commit_exists(str(repo), sha), True)
            self.assertEqual(len(calls), 2)                     # idx and pack
            self.assertIs(commit_exists(str(repo), sha), True)
            self.assertEqual(len(calls), 2)                     # cached
            _, packfile = pack_files(repo)
            packfile.chmod(0o600)                               # ctime moves
            self.assertIs(commit_exists(str(repo), sha), True)
            self.assertEqual(len(calls), 4)

    def test_malformed_arguments(self):
        repo, shas = self.loose["sha1"]
        for sha in (None, 1, True, 1.5, [], "", "A" * 40, shas[0].upper(), shas[0][:39], shas[0] + "0",
                    "g" * 40, " " + shas[0][1:], "a" * 63, "a" * 65, shas[0] + "\n"):
            with self.subTest(sha=repr(sha)[:20]):
                self.assertIsNone(commit_exists(str(repo), sha))
        for workdir in (None, 1, True, "", "relative/path", "/no/such/dir", "/tmp\0x", b"/tmp", str(repo) + "/./.."):
            with self.subTest(workdir=repr(workdir)[:30]):
                self.assertIsNone(commit_exists(workdir, shas[0]))


if __name__ == "__main__":
    unittest.main()
