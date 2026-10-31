#!/usr/bin/env python3
""".github/: workflow wiring, release logic and release notes.

The resolve and release steps are run for real, against a scratch git
repository and a fake gh, so the tag, re-cut and Latest decisions are tested
without GitHub.
"""

import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "build.yml"
BIONIC_CI = ROOT / ".github" / "ci" / "bionic-build.sh"
NATIVES_CI = ROOT / ".github" / "ci" / "natives.sh"
BASH = shutil.which("bash")

MANIFEST = {
    "opencode": "1.2.4",
    "source": {"tag": "v1.2.4", "commit": "f" * 40},
    "output_sha256": "output-hash",
    "base_bun": {"version": "1.4.3+c6da4a4d3"},
    "native_assets": {"result": "pass"},
    "tui_smoke": "pass",
    "release_eligible": True,
}


def run_block(header):
    """The shell of the workflow step whose first line is `header`."""
    lines = WORKFLOW.read_text().splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == header)
    run = next(i for i in range(start, len(lines)) if lines[i].strip() == "run: |")
    indent = len(lines[run]) - len(lines[run].lstrip()) + 2
    body = []
    for line in lines[run + 1:]:
        if line.strip() and len(line) - len(line.lstrip()) < indent:
            break
        body.append(line[indent:])
    return "\n".join(body) + "\n"


def git(repo, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "init.defaultBranch=main",
         *args], cwd=repo, text=True, capture_output=True, check=True,
    ).stdout.strip()


def commit(repo, path, subject):
    target = pathlib.Path(repo) / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(subject)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", subject)
    return git(repo, "rev-parse", "HEAD")


class ReleaseNotesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = ROOT / ".github" / "release_notes.py"
        spec = importlib.util.spec_from_file_location("release_notes", path)
        cls.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.module)

    def test_hashes_base_install_command_and_changes(self):
        notes = self.module.release_notes(MANIFEST, "v1.2.4", "c" * 40, "v1.2.3",
                                          "abc1234 build: change")
        self.assertIn("`v1.2.4` · `ffffffffffff`", notes)
        self.assertIn("output-hash", notes)
        self.assertIn("1.4.3+c6da4a4d3", notes)
        self.assertIn("`cccccccccccc`", notes)
        self.assertIn("main/install.sh | bash", notes)
        self.assertIn("相对 `v1.2.3` 的工具链变更", notes)
        self.assertIn("abc1234 build: change", notes)
        self.assertNotIn("重新发布", notes)

    def test_lists_the_native_versions_it_was_built_with(self):
        manifest = dict(MANIFEST, natives={"opentui": {"version": "0.8.0"}, "fff": {"version": "0.10.5"},
                                           "rust_pty": {"version": "0.4.11"}})
        notes = self.module.release_notes(manifest, "v1.2.4", "c" * 40, "-", "")
        self.assertIn("OpenTUI 0.8.0 · FFF 0.10.5 · bun-pty 0.4.11", notes)

    def test_reports_bionic_acceptance(self):
        notes = self.module.release_notes(MANIFEST, "v1.2.4", "c" * 40, "-", "")
        self.assertIn("从 OpenCode 源码编译", notes)
        self.assertIn("真实 TUI 启动全部通过", notes)
        self.assertIn("（无）", notes)
        failed = dict(MANIFEST, tui_smoke="skipped-cross-build", release_eligible=False)
        self.assertIn("未完成 Bionic 运行验收",
                      self.module.release_notes(failed, "v1.2.4", "c", "-", ""))

    def test_recut_says_what_changed_and_how_to_get_it(self):
        notes = self.module.release_notes(MANIFEST, "v1.2.4-r2", "c" * 40, "v1.2.4-r1", "x")
        self.assertIn("第 2 次重新发布", notes)
        self.assertIn("按二进制哈希判断", notes)
        self.assertIn("重新运行一次下面的安装命令", notes)


class ResolveTests(unittest.TestCase):
    def resolve(self, tags, requested, recut):
        with tempfile.TemporaryDirectory() as repo:
            git(repo, "init", "-q")
            commit(repo, "a", "a")
            for tag in tags:
                git(repo, "tag", tag)
            output = pathlib.Path(repo) / "github-output"
            env = dict(os.environ, REQUESTED=requested, RECUT=recut, GITHUB_OUTPUT=str(output))
            proc = subprocess.run([BASH, "-c", run_block("- name: Resolve requested OpenCode version")],
                                  cwd=repo, env=env, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return dict(line.split("=", 1) for line in output.read_text().split())

    def test_new_version_is_released_as_plain_tag(self):
        out = self.resolve(["v1.2.3"], "1.2.4", "false")
        self.assertEqual((out["tag"], out["unreleased"]), ("v1.2.4", "true"))

    def test_released_version_is_not_released_again(self):
        out = self.resolve(["v1.2.3"], "v1.2.3", "false")
        self.assertEqual(out["unreleased"], "false")

    def test_recut_counts_as_released(self):
        out = self.resolve(["v1.2.3-r1"], "1.2.3", "false")
        self.assertEqual(out["unreleased"], "false")

    def test_recut_takes_the_next_free_suffix(self):
        out = self.resolve(["v1.2.3", "v1.2.3-r1"], "1.2.3", "true")
        self.assertEqual((out["tag"], out["unreleased"]), ("v1.2.3-r2", "true"))


class PublishTests(unittest.TestCase):
    """Runs the release job's shell against a scratch repository and a fake gh."""

    PACKAGE = "opencode-termux-v1.2.4-android-aarch64"

    def publish(self, tags, version, tag, fail_first=False):
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp) / "repo"
            repo.mkdir()
            git(repo, "init", "-q")
            commit(repo, "scripts/x.sh", "first")
            for t in tags:
                git(repo, "tag", t)
            commit(repo, "scripts/x.sh", "build: change the graft")
            head = commit(repo, "docs/x.md", "docs: explain it")
            shutil.copytree(ROOT / ".github", repo / ".github")
            artifact = repo / "artifact"
            artifact.mkdir()
            package = f"opencode-termux-v{version}-android-aarch64"
            (artifact / f"{package}.zip").write_bytes(b"zip")
            digest = hashlib.sha256(b"zip").hexdigest()
            (artifact / f"{package}.zip.sha256").write_text(f"{digest}  {package}.zip\n")
            (artifact / "build-manifest.json").write_text(json.dumps(dict(MANIFEST, opencode=version)))
            calls = pathlib.Path(tmp) / "calls.jsonl"
            fake = pathlib.Path(tmp) / "bin"
            fake.mkdir()
            (fake / "gh").write_text(f"""#!{sys.executable}
import json, os, sys
calls = {str(calls)!r}
n = sum(1 for _ in open(calls)) if os.path.exists(calls) else 0
with open(calls, "a") as f:
    f.write(json.dumps({{"args": sys.argv[1:], "notes": open("notes.md").read()}}) + "\\n")
if {fail_first!r} and n == 0:
    print("HTTP 422: tag_name was used by an immutable release", file=sys.stderr)
    sys.exit(1)
""")
            (fake / "gh").chmod(0o755)
            env = dict(os.environ, PATH=f"{fake}:{os.environ['PATH']}", GITHUB_SHA=head,
                       VERSION=version, TAG=tag, PACKAGE=package)
            proc = subprocess.run([BASH, "-c", run_block("- name: Publish verified Bionic release")],
                                  cwd=repo, env=env, text=True, capture_output=True)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            return head, [json.loads(line) for line in calls.read_text().splitlines()]

    def test_pins_the_built_commit_attaches_the_package_and_lists_changes(self):
        head, calls = self.publish(["v1.2.3"], "1.2.4", "v1.2.4")
        self.assertEqual(len(calls), 1)
        args, notes = calls[0]["args"], calls[0]["notes"]
        self.assertEqual(args[:3], ["release", "create", "v1.2.4"])
        self.assertEqual(args[args.index("--target") + 1], head)
        self.assertIn("--latest=true", args)
        for asset in (f"{self.PACKAGE}.zip", f"{self.PACKAGE}.zip.sha256", "build-manifest.json"):
            self.assertIn(f"artifact/{asset}", args)
        self.assertNotIn("--clobber", args)
        self.assertIn("build: change the graft", notes)
        self.assertNotIn("docs: explain it", notes)

    def test_predecessor_is_the_highest_release_on_a_shared_commit(self):
        _, calls = self.publish(["v1.2.2", "v1.2.3"], "1.2.4", "v1.2.4")
        self.assertIn("相对 `v1.2.3` 的工具链变更", calls[0]["notes"])

    def test_recut_of_the_latest_version_takes_latest(self):
        _, calls = self.publish(["v1.2.3"], "1.2.3", "v1.2.3-r1")
        self.assertIn("--latest=true", calls[0]["args"])
        self.assertIn("OpenCode 1.2.3 · Termux (r1)", calls[0]["args"])

    def test_recut_of_an_older_version_does_not_take_latest(self):
        _, calls = self.publish(["v1.2.3", "v1.2.5"], "1.2.3", "v1.2.3-r1")
        self.assertIn("--latest=false", calls[0]["args"])
        self.assertIn("第 1 次重新发布", calls[0]["notes"])

    def test_reserved_tag_falls_back_to_next_recut(self):
        _, calls = self.publish(["v1.2.3"], "1.2.4", "v1.2.4", fail_first=True)
        self.assertEqual([c["args"][2] for c in calls], ["v1.2.4", "v1.2.4-r1"])
        self.assertIn("第 1 次重新发布", calls[1]["notes"])


class WorkflowWiringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()
        cls.script = BIONIC_CI.read_text()

    def test_manual_runs_recut_instead_of_overwriting(self):
        self.assertIn("recut:", self.workflow)
        self.assertNotIn("publish:", self.workflow)
        self.assertNotIn("--clobber", self.workflow)
        self.assertIn("if: needs.resolve.outputs.unreleased == 'true' && github.ref == 'refs/heads/main'",
                      self.workflow)

    def test_only_the_release_job_can_write(self):
        self.assertEqual(self.workflow.count("contents: write"), 1)
        release = self.workflow.split("\n  release:", 1)[1]
        self.assertIn("contents: write", release)

    def test_uses_pinned_termux_image_on_native_arm_runner(self):
        self.assertIn("runs-on: ubuntu-24.04-arm", self.workflow)
        self.assertRegex(self.workflow, r"termux/termux-docker@sha256:[0-9a-f]{64}")

    def test_bionic_path_compiles_from_source_and_executes_the_candidate(self):
        self.assertNotIn("SKIP_RUN", self.script)
        self.assertIn("bash .github/ci/natives.sh", self.script)
        self.assertIn("make build-native", NATIVES_CI.read_text())
        self.assertIn("make verify", self.script)
        self.assertIn("make fetch-source", self.workflow)
        self.assertIn("make compile", self.workflow)
        resolved, natives, compile_, verify = (self.workflow.index(step) for step in (
            "make resolve-natives", "bionic-build.sh natives", "make compile", "bionic-build.sh verify"))
        self.assertLess(resolved, natives)
        self.assertLess(natives, compile_)
        self.assertLess(compile_, verify)
        self.assertIn('assert doc["tui_smoke"] == "pass"', self.workflow)
        self.assertIn('assert doc["release_eligible"] is True', self.workflow)


if __name__ == "__main__":
    unittest.main()
