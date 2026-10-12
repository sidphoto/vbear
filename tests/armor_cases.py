"""The cases the armor (seven launch labels) tests run: shared by the golden file and its test.

``render`` calls ``agent_launch.derive_labels`` exactly as the preview does, with the two outside facts the labels
depend on (the network-verified switch and the Codex evidence record) and the local verified-versions record set by
the case, and returns the JSON text of the result (key order included).
"""

from __future__ import annotations

import json
from unittest import mock

from vbear import agent_launch
from vbear.runtime import cli_versions

SHA = "a" * 64
SCRATCH = "/private/tmp/sc-0123456789ab"
WORKDIR = "/Users/example/projects/demo"


def _manifest(engine, version, verified=None):
    m = {"engine": engine, "cli_version": version, "settings_sha256": SHA, "scratch": {"path": SCRATCH}}
    if verified is not None:
        m["cli_verified"] = verified
    return m


MANIFESTS = {
    "claude_verified_builtin": _manifest("claude", "2.1.296", True),
    "claude_verified_local": _manifest("claude", "2.1.900", True),
    "claude_unverified": _manifest("claude", "2.1.999", False),
    "claude_no_version": {"engine": "claude", "cli_verified": True},
    "codex": _manifest("codex", "0.159.2"),
    "none_claude": None,
    "none_codex": None,
}
ENGINES = {"none_claude": "claude", "none_codex": "codex"}
LOCAL_RECORDS = {"2.1.900": {"report": "/Users/example/.vbear/reports/claude-2.1.900.json", "passed": True}}


def cases():
    out = []
    for name in MANIFESTS:
        for workdir in (WORKDIR, None):
            for network in (True, False):
                for codex_ok in (True, False):
                    out.append({"manifest": name, "workdir": workdir, "network_verified": network,
                                "codex_evidence": codex_ok})
    return out


def render(case) -> str:
    manifest = MANIFESTS[case["manifest"]]
    with mock.patch.object(agent_launch, "NETWORK_VERIFIED", case["network_verified"]), \
         mock.patch.object(agent_launch, "_codex_evidence_reference",
                           return_value="docs/evidence/codex-0.159.2.json" if case["codex_evidence"] else None), \
         mock.patch.object(cli_versions, "local_verified_versions", return_value=dict(LOCAL_RECORDS)):
        labels = agent_launch.derive_labels(manifest, case["workdir"], ENGINES.get(case["manifest"]))
    return json.dumps(labels, ensure_ascii=False)


def golden() -> list:
    return [{"case": c, "labels": render(c)} for c in cases()]


if __name__ == "__main__":
    import sys
    json.dump(golden(), sys.stdout, ensure_ascii=False, indent=1)
