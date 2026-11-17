"""Offline permission regressions: synthetic trees/proc only, no deployment."""
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


TEXT = (Path(__file__).parent / "dpms-node.sh").read_text()


def function(name):
    return re.search(r"^" + name + r"\(\) \{\n.*?^\}", TEXT, re.M | re.S).group(0)


PREPARE = function("prepare_frontend_public_permissions")
COPY = function("copy_runtime_files_from_release")
PYTHON = re.search(r"<<'PY'\n(.*?)\nPY", PREPARE, re.S).group(1)


def helper():
    namespace = {"__name__": "synthetic_frontend_check"}
    exec(compile(PYTHON, "<frontend-permissions>", "exec"), namespace)
    return namespace


# Execute the actual embedded helper, replacing only host discovery/identity and
# optionally injecting a kernel read denial. Never inspect the caller's /proc.
PYTHON_STUB = r'''
import os
from pathlib import Path
import sys
from unittest.mock import patch

ns = {"__name__": "synthetic_frontend_check"}
exec(compile(sys.stdin.read(), "<frontend-permissions>", "exec"), ns)
def identity():
    if os.environ["FAIL_GATE"] == "identity":
        raise ValueError("synthetic unavailable identity")
    return os.getuid(), os.getgid(), tuple(os.getgroups())
ns["nginx_worker_identity"] = identity
real_open = os.open
def read_open(path, flags, *args, **kwargs):
    if os.environ["FAIL_GATE"] == "read" and Path(path).name == "index.html":
        raise PermissionError("synthetic nginx read denial")
    return real_open(path, flags, *args, **kwargs)
try:
    with patch.object(os, "setgroups"), patch.object(os, "setgid"), patch.object(os, "setuid"), patch.object(os, "open", read_open):
        ns["main"](sys.argv[2])
except (OSError, ValueError):
    sys.exit("synthetic nginx gate rejected candidate")
'''


class FrontendPublicationTests(unittest.TestCase):
    def run_copy(self, mask, *, failure="", directory_live=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        live, release = root / "live", root / "candidate"
        live.mkdir(mode=0o755)
        private = [live / name for name in ("backend", "deploy", "backups", "logs")]
        for path in private:
            path.mkdir(mode=0o700)
            (path / "fixture.txt").write_text("private synthetic fixture")
            (path / "fixture.txt").chmod(0o600)
        dist = release / "frontend/dist"
        (dist / "assets/nested").mkdir(parents=True)
        (dist / "index.html").write_text("synthetic new index")
        (dist / "assets/nested/app.js").write_text("synthetic asset")
        for path in [dist, *dist.rglob("*")]:
            path.chmod(0o700 if path.is_dir() else 0o600)
        (live / "frontend").mkdir(mode=0o755)
        old = root / "old-dist"
        old.mkdir()
        (old / "index.html").write_text("synthetic old index")
        link = live / "frontend/dist"
        if directory_live:
            link.mkdir()
            (link / "index.html").write_text("synthetic old index")
        else:
            link.symlink_to(old)
        executable = root / "python3"
        executable.write_text("#!" + sys.executable + "\n" + PYTHON_STUB)
        executable.chmod(0o755)
        # GNU ln -T is replaced on macOS; the replacement rejects unexpected args.
        link_stub = root / "ln"
        link_stub.write_text("#!" + sys.executable + "\n" + '''
import os
from pathlib import Path
import sys
assert sys.argv[1] == "-sfnT" and len(sys.argv) == 4
destination = Path(sys.argv[3])
if destination.is_symlink():
    destination.unlink()
os.symlink(sys.argv[2], destination)
''')
        link_stub.chmod(0o755)
        script = """set -euo pipefail
die() { printf '%s\\n' "$*" >&2; exit 1; }
rsync() { :; }
umask "$TEST_UMASK"
before=$(umask)
""" + PREPARE + "\n" + COPY + '''
copy_runtime_files_from_release "$CANDIDATE"
[[ "$(umask)" == "$before" ]]
'''
        result = subprocess.run(["bash", "-c", script], capture_output=True, text=True, timeout=10, env={
            "PATH": str(root) + os.pathsep + os.defpath,
            "DPMS_LIVE_ROOT": str(live), "CANDIDATE": str(release),
            "TEST_UMASK": mask, "FAIL_GATE": failure,
        })
        for path in private:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE((path / "fixture.txt").stat().st_mode), 0o600)
            self.assertEqual((path / "fixture.txt").read_text(), "private synthetic fixture")
        self.assertEqual(stat.S_IMODE(live.stat().st_mode), 0o755)
        return result, live, old, link

    def test_restrictive_and_normal_umasks_publish_only_public_modes(self):
        for mask in ("0077", "0022"):
            with self.subTest(mask=mask):
                result, live, _, link = self.run_copy(mask)
                self.assertEqual(result.returncode, 0, result.stderr)
                release = live / "frontend/releases/candidate"
                self.assertEqual(link.readlink(), release / "dist")
                for directory in (live / "frontend", live / "frontend/releases", release):
                    self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o755)
                for path in [release / "dist", *(release / "dist").rglob("*")]:
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755 if path.is_dir() else 0o644)
                self.assertEqual((link / "index.html").read_text(), "synthetic new index")

    def test_gate_failure_preserves_symlink_and_legacy_directory(self):
        for failure in ("read", "identity"):
            for directory_live in (False, True):
                with self.subTest(failure=failure, directory_live=directory_live):
                    result, live, old, link = self.run_copy("0077", failure=failure, directory_live=directory_live)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("symlink unchanged", result.stderr)
                    self.assertEqual(link.is_symlink(), not directory_live)
                    if not directory_live:
                        self.assertEqual(link.readlink(), old)
                    self.assertEqual((link / "index.html").read_text(), "synthetic old index")
                    self.assertEqual(list((live / "frontend").glob("dist.previous.*")), [])


class NginxAccessTests(unittest.TestCase):
    def setUp(self):
        self.ns = helper()
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.proc = self.root / "proc"
        (self.proc / "self/ns").mkdir(parents=True)
        (self.proc / "self/ns/mnt").touch()

    def worker(self, pid="101", uid=33, *, root=None, mount=True, groups="33"):
        process = self.proc / pid
        (process / "ns").mkdir(parents=True)
        (process / "comm").write_text("nginx\n")
        (process / "status").write_text(f"Uid:\t{uid} {uid} {uid} {uid}\nGid:\t33 33 33 33\nGroups:\t{groups}\n")
        (process / "root").symlink_to(root or "/")
        if mount:
            os.link(self.proc / "self/ns/mnt", process / "ns/mnt")
        else:
            (process / "ns/mnt").touch()
        return process

    def test_discovery_uses_worker_identity_not_root_master(self):
        self.worker("100", uid=0)
        self.worker("101")
        self.worker("102")
        self.assertEqual(self.ns["nginx_worker_identity"](self.proc), (33, 33, (33,)))

    def test_missing_conflicting_or_isolated_workers_fail_closed(self):
        with self.assertRaises(ValueError):
            self.ns["nginx_worker_identity"](self.proc)
        process = self.worker(root=self.root)
        with self.assertRaises(ValueError):
            self.ns["nginx_worker_identity"](self.proc)
        (process / "root").unlink()
        (process / "root").symlink_to("/")
        (process / "ns/mnt").unlink()
        (process / "ns/mnt").touch()
        with self.assertRaises(ValueError):
            self.ns["nginx_worker_identity"](self.proc)
        (process / "ns/mnt").unlink()
        os.link(self.proc / "self/ns/mnt", process / "ns/mnt")
        self.worker("102", groups="33 44")
        with self.assertRaises(ValueError):
            self.ns["nginx_worker_identity"](self.proc)

    def test_probe_drops_groups_gid_uid_before_access_and_checks_ancestors(self):
        events = []
        self.ns["nginx_worker_identity"] = lambda: (33, 33, (33,))
        self.ns["normalize_public_tree"](self.root)
        def access(path, mode, **kwargs):
            self.assertEqual(events[:3], [("groups", (33,)), ("gid", 33), ("uid", 33)])
            self.assertTrue(kwargs["effective_ids"])
            events.append(("access", path))
            return path != self.root.parent
        with patch.object(os, "setgroups", side_effect=lambda value: events.append(("groups", value))), \
             patch.object(os, "setgid", side_effect=lambda value: events.append(("gid", value))), \
             patch.object(os, "setuid", side_effect=lambda value: events.append(("uid", value))), \
             patch.object(os, "access", side_effect=access):
            with self.assertRaises(PermissionError):
                self.ns["check_nginx_access"](self.root)

    def test_static_symlinks_rejected_without_chmod_of_private_target(self):
        private = self.root / "private-area"
        private.mkdir(mode=0o700)
        file = private / "fixture.txt"
        file.write_text("private fixture")
        file.chmod(0o600)
        public = self.root / "public"
        public.mkdir()
        (public / "outside").symlink_to(private)
        with self.assertRaises(ValueError):
            self.ns["normalize_public_tree"](public)
        self.assertEqual(stat.S_IMODE(private.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(file.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
