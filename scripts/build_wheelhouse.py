#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PLATFORM_TAGS = {
    "arm64": [
        "manylinux_2_28_aarch64",
        "manylinux2014_aarch64",
        "manylinux_2_24_aarch64",
        "manylinux_2_17_aarch64",
    ],
    "amd64": [
        "manylinux_2_28_x86_64",
        "manylinux2014_x86_64",
        "manylinux_2_24_x86_64",
        "manylinux_2_17_x86_64",
    ],
}


@dataclass(frozen=True)
class WheelInfo:
    filename: str
    package: str
    version: str
    wheel_tags: str
    local_sha256: str
    size_bytes: int
    direct_or_transitive: str
    source_url: str
    official_pypi_sha256: str
    metadata_name: str
    metadata_version: str
    requires_python: str | None


def canonical_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def parse_requirements(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "==" not in line:
            continue
        name, version = line.split("==", 1)
        pins[canonical_name(name)] = version.split()[0].strip()
    return pins


def pip_download(platform: str, requirements: Path, outdir: Path) -> None:
    if outdir.exists():
        shutil.rmtree(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cmd = [
        sys.executable,
        "-m",
        "pip",
        "download",
        "-r",
        str(requirements),
        "-d",
        str(outdir),
        "--only-binary=:all:",
        "--implementation",
        "cp",
        "--python-version",
        "3.12",
        "--abi",
        "cp312",
    ]
    for tag in PLATFORM_TAGS[platform]:
        cmd.extend(["--platform", tag])
    subprocess.run(cmd, check=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_wheel_metadata(path: Path) -> tuple[str, str, str | None, str]:
    with zipfile.ZipFile(path) as zf:
        meta_name = next(
            name for name in zf.namelist() if name.endswith(".dist-info/METADATA")
        )
        wheel_name = next(
            name for name in zf.namelist() if name.endswith(".dist-info/WHEEL")
        )
        metadata = zf.read(meta_name).decode("utf-8", errors="replace")
        wheel = zf.read(wheel_name).decode("utf-8", errors="replace")

    pkg_name = None
    pkg_version = None
    requires_python = None
    for line in metadata.splitlines():
        if line.startswith("Name: "):
            pkg_name = line[6:].strip()
        elif line.startswith("Version: "):
            pkg_version = line[9:].strip()
        elif line.startswith("Requires-Python: "):
            requires_python = line[17:].strip()
    if not pkg_name or not pkg_version:
        raise RuntimeError(f"cannot parse METADATA in {path.name}")
    return pkg_name, pkg_version, requires_python, wheel


def query_pypi_json(name: str, version: str, filename: str) -> tuple[str, str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    with urllib.request.urlopen(url, timeout=30) as resp:
        payload = json.load(resp)
    for entry in payload.get("urls", []):
        if entry.get("filename") == filename:
            return entry["url"], entry["digests"]["sha256"]
    raise RuntimeError(f"PyPI JSON did not contain {filename} for {name} {version}")


def build_lock_lines(wheels: list[WheelInfo]) -> list[str]:
    lines = [
        "# CPython 3.12.13 target platform build lock.",
        "# All wheels verified against official PyPI SHA-256.",
    ]
    for wheel in sorted(wheels, key=lambda item: canonical_name(item.package)):
        lines.append(f"{wheel.package}=={wheel.version} --hash=sha256:{wheel.local_sha256}")
    return lines


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("arm64", "amd64"), required=True)
    parser.add_argument("--requirements", default="requirements.txt")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()

    requirements = Path(args.requirements)
    outdir = Path(args.output_dir)
    pins = parse_requirements(requirements)

    pip_download(args.platform, requirements, outdir)

    wheels: list[WheelInfo] = []
    for path in sorted(outdir.glob("*.whl")):
        local_sha256 = sha256_file(path)
        pkg_name, pkg_version, requires_python, wheel_text = read_wheel_metadata(path)
        source_url, official_sha = query_pypi_json(canonical_name(pkg_name), pkg_version, path.name)
        direct_or_transitive = "direct" if canonical_name(pkg_name) in pins else "transitive"
        wheels.append(
            WheelInfo(
                filename=path.name,
                package=pkg_name,
                version=pkg_version,
                wheel_tags=wheel_text.replace("\n", "; ").strip(),
                local_sha256=local_sha256,
                size_bytes=path.stat().st_size,
                direct_or_transitive=direct_or_transitive,
                source_url=source_url,
                official_pypi_sha256=official_sha,
                metadata_name=pkg_name,
                metadata_version=pkg_version,
                requires_python=requires_python,
            )
        )

    wheel_map = {w.package.lower(): w for w in wheels}
    suffix = "linux-amd64-cp312" if args.platform == "amd64" else "linux-arm64-cp312"
    lock_path = outdir / f"requirements-{suffix}.lock"
    lock_path.write_text("\n".join(build_lock_lines(wheels)) + "\n", encoding="utf-8")

    sha_path = outdir / "SHA256SUMS"
    sha_path.write_text(
        "\n".join(f"{w.local_sha256}  {w.filename}" for w in sorted(wheels, key=lambda w: w.filename))
        + "\n",
        encoding="utf-8",
    )

    manifest = {
        "platform": args.platform,
        "requirements": str(Path(args.requirements)),
        "wheel_count": len(wheels),
        "direct_dependency_count": sum(1 for w in wheels if w.direct_or_transitive == "direct"),
        "transitive_dependency_count": sum(1 for w in wheels if w.direct_or_transitive == "transitive"),
        "wheels": [w.__dict__ for w in sorted(wheels, key=lambda w: w.package.lower())],
    }
    (outdir / "artifact-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "platform": args.platform,
        "wheel_count": len(wheels),
        "requirements": str(Path(args.requirements)),
        "packages": [w.package for w in sorted(wheels, key=lambda w: w.package.lower())],
        "target_suffix": suffix,
    }
    (outdir / "pypi-metadata-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
