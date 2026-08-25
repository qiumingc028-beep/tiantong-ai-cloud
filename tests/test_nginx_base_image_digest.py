import copy
import json
import re
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile.frontend"
OCI_INDEX_DIGEST = "sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10"
EXPECTED_REFERENCE = "nginx:1.27-alpine@" + OCI_INDEX_DIGEST
EXPECTED_METADATA = {
    "tag": "1.27-alpine",
    "platform": "linux/amd64",
    "os": "linux",
    "architecture": "amd64",
    "oci_index_digest": OCI_INDEX_DIGEST,
    "linux_amd64_manifest_digest": "sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8",
    "config_digest": "sha256:6769dc3a703c719c1d2756bda113659be28ae16cf0da58dd5fd823d6b9a050ea",
}
DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)


def validate(dockerfile_path, metadata):
    path = Path(dockerfile_path)
    if path.is_symlink() or not path.is_file() or path.resolve() != DOCKERFILE:
        return "dockerfile_path"
    return validate_text(path.read_text(encoding="ascii"), metadata)


def validate_text(text, metadata):
    from_lines = [line for line in text.splitlines() if line.startswith("FROM ")]
    if len(from_lines) != 1:
        return "from_count"
    reference = from_lines[0][5:]
    if reference != EXPECTED_REFERENCE or ":latest" in reference:
        return "base_reference"
    reference_digest = reference.rsplit("@", 1)[-1]
    for key in ("oci_index_digest", "linux_amd64_manifest_digest", "config_digest"):
        value = metadata.get(key)
        if not isinstance(value, str) or DIGEST.fullmatch(value) is None:
            return key + "_format"
    if metadata.get("tag") != "1.27-alpine":
        return "tag"
    if reference_digest != metadata.get("oci_index_digest"):
        return "reference_index_binding"
    if metadata.get("platform") != "linux/amd64":
        return "platform"
    if metadata.get("os") != "linux" or metadata.get("architecture") != "amd64":
        return "platform_descriptor"
    if metadata != EXPECTED_METADATA:
        return "digest_domain_binding"
    if not (ROOT / "nginx/default.conf").is_file() or not (ROOT / "frontend").is_dir():
        return "build_context"
    return "ok"


class NginxBaseImageDigestTest(unittest.TestCase):
    failure_injection_count = 0

    def test_fixed_release_contract(self):
        self.assertEqual(validate(DOCKERFILE, EXPECTED_METADATA), "ok")

    def test_failure_injections(self):
        cases = []
        for name, key, value in (
            ("short_digest", "oci_index_digest", "sha256:" + "0" * 63),
            ("non_ascii", "oci_index_digest", "sha256:" + "0" * 63 + "é"),
            ("uppercase_hex", "oci_index_digest", "sha256:" + "A" * 64),
            ("digest_replacement", "oci_index_digest", "sha256:" + "0" * 64),
            ("wrong_arch", "architecture", "arm64"),
            ("wrong_os", "os", "darwin"),
            ("wrong_platform", "platform", "linux/arm64"),
            ("tag_drift", "tag", "1.28-alpine"),
            ("manifest_as_index", "oci_index_digest", EXPECTED_METADATA["linux_amd64_manifest_digest"]),
            ("config_as_index", "oci_index_digest", EXPECTED_METADATA["config_digest"]),
        ):
            metadata = copy.deepcopy(EXPECTED_METADATA)
            metadata[key] = value
            cases.append((name, DOCKERFILE, metadata))

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            replacement = root / "replacement"
            replacement.write_text(DOCKERFILE.read_text(encoding="ascii"), encoding="ascii")
            cases.append(("path_replacement", replacement, EXPECTED_METADATA))
            link = root / "Dockerfile.link"
            link.symlink_to(DOCKERFILE)
            cases.append(("symlink", link, EXPECTED_METADATA))
            for name, path, metadata in cases:
                with self.subTest(name=name):
                    self.assertNotEqual(validate(path, metadata), "ok")
        text = DOCKERFILE.read_text(encoding="ascii")
        text_cases = (
            ("multiple_from", text + "FROM nginx:latest\n"),
            ("latest", text.replace(EXPECTED_REFERENCE, "nginx:latest")),
        )
        type(self).failure_injection_count = len(cases) + len(text_cases)
        for name, candidate in text_cases:
            with self.subTest(name=name):
                self.assertNotEqual(validate_text(candidate, EXPECTED_METADATA), "ok")


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=0).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(NginxBaseImageDigestTest)
    )
    print(json.dumps({"errors": len(result.errors), "failure_injections": NginxBaseImageDigestTest.failure_injection_count, "failures": len(result.failures), "tests": result.testsRun}, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)
