#!/usr/bin/python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Safely rebuild a small local KWin patch against KDE neon updates."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STATE = Path("/var/lib/kwin-ctm-monitor")
CACHE = Path("/var/cache/kwin-ctm-monitor")
RUNTIME = Path("/run/kwin-ctm-monitor")
STATUS = STATE / "status.json"
CONFIG = Path("/etc/kwin-ctm-monitor.conf")
PATCH = Path("/usr/share/kwin-ctm-monitor/patches/custom-output-ctm.patch")
NEON_SOURCES = Path("/etc/apt/sources.list.d/neon.sources")
NEON_KEY = Path("/etc/apt/keyrings/neon-archive-keyring.asc")
DRM_CLASS = Path("/sys/class/drm")
LOCAL_SOURCE = Path("/etc/apt/sources.list.d/kwin-ctm-monitor.sources")

PACKAGES = ("kwin-wayland", "kwin-common", "kwin-data", "kwin-dev")


class MonitorError(RuntimeError):
    pass


def run(args: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    proc = subprocess.run(
        args,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        check=False,
    )
    if proc.returncode:
        detail = proc.stdout.strip() if proc.stdout else f"exit status {proc.returncode}"
        raise MonitorError(f"{' '.join(args)}: {detail}")
    return proc.stdout if proc.stdout else ""


def load_config() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in CONFIG.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_status(state: str, **details: object) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    payload = {"state": state, "updated_at": int(time.time()), **details}
    with tempfile.NamedTemporaryFile("w", dir=STATE, delete=False, encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o644)
    os.replace(temporary, STATUS)


def versions_from_madison() -> list[str]:
    output = run(["apt-cache", "madison", "kwin-wayland"], capture=True)
    versions = []
    for line in output.splitlines():
        fields = [part.strip() for part in line.split("|")]
        if len(fields) >= 2 and "zneon" in fields[1] and "+ctm" not in fields[1]:
            versions.append(fields[1])
    if not versions:
        raise MonitorError("no unpatched KDE neon kwin-wayland version found")
    versions.sort(key=DebianVersion)
    return versions


class DebianVersion:
    def __init__(self, value: str):
        self.value = value

    def __lt__(self, other: "DebianVersion") -> bool:
        result = subprocess.run(["dpkg", "--compare-versions", self.value, "lt", other.value])
        return result.returncode == 0


def upstream_version(package_version: str) -> str:
    value = package_version.split(":", 1)[-1]
    match = re.match(r"([0-9]+(?:\.[0-9]+){2})-", value)
    if not match:
        raise MonitorError(f"cannot derive KWin tag from {package_version!r}")
    return match.group(1)


def already_published(version: str) -> bool:
    if not STATUS.exists():
        return False
    try:
        data = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return data.get("state") == "published" and data.get("neon_version") == version


@contextlib.contextmanager
def exclusive_lock():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    lock_path = RUNTIME / "monitor.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise MonitorError("another monitor build is already running") from exc
        yield


def prepare_source(work: Path, version: str) -> Path:
    # KDE neon publishes deb-src metadata. Fetching the candidate's exact source
    # package is safer than combining an upstream tag with a moving packaging
    # branch and guarantees that build dependencies match the binary candidate.
    run(["apt-get", "source", f"kwin={version}"], cwd=work)
    candidates = [path for path in work.iterdir() if path.is_dir() and (path / "debian" / "control").exists()]
    if len(candidates) != 1:
        raise MonitorError(f"expected one extracted KWin source tree, found {len(candidates)}")
    source = candidates[0]
    run(["patch", "--batch", "--forward", "--fuzz=0", "-p1", "-i", str(PATCH)], cwd=source)
    return source


def find_vkms_node(drm_class: Path = DRM_CLASS, dev_root: Path = Path("/dev/dri")) -> Path:
    """Return the VKMS primary node, identified by its kernel driver."""
    for card in sorted(drm_class.glob("card[0-9]*")):
        device = card / "device"
        driver = device / "driver"
        try:
            device_name = device.resolve(strict=True).name
            driver_name = driver.resolve(strict=True).name
        except OSError:
            continue
        if device_name != "vkms" or driver_name != "faux_driver":
            continue
        node = dev_root / card.name
        if node.exists() and node.is_char_device():
            return node
    raise MonitorError("VKMS DRM node not found; verify that the vkms module is loaded")


def build_in_docker(source: Path, output: Path, image: str, vkms_node: Path, local_version: str) -> None:
    output.mkdir(parents=True, exist_ok=True)
    script = r"""
set -eu
export DEBIAN_FRONTEND=noninteractive
cp /host/neon.sources /etc/apt/sources.list.d/neon.sources
mkdir -p /etc/apt/keyrings
cp /host/neon-archive-keyring.asc /etc/apt/keyrings/neon-archive-keyring.asc
apt-get update
apt-get install -y --no-install-recommends build-essential ca-certificates dbus-x11 debhelper devscripts equivs git pkg-kde-tools-neon x11-utils xauth xvfb
cd "/build/$SOURCE_BASENAME"
export DEBEMAIL=local@kwin-ctm.invalid
export DEBFULLNAME='KWin CTM Monitor'
dch --newversion "$LOCAL_VERSION" 'Apply configurable per-output SDR CTM support.'
mk-build-deps --install --remove --tool 'apt-get -y --no-install-recommends' debian/control

# Configure tests explicitly, then build and execute representative unit and
# DRM coverage in the same environment used by KDE's Debian test runner.
debian/rules override_dh_auto_configure
dh_auto_build --buildsystem=kf6 -- testWindowPaintData testColorspaces testMockDrm
export LANG=C.UTF-8
export HOME=/tmp/kwin-test-home
export XDG_RUNTIME_DIR=/tmp/kwin-test-runtime
mkdir -p "$HOME/.config" "$HOME/.kde-unit-test" "$XDG_RUNTIME_DIR"
chmod 0700 "$XDG_RUNTIME_DIR"
Xvfb :99 -screen 0 1024x768x24 -ac -nolisten tcp \
    +extension RANDR +extension RENDER +extension GLX >/tmp/xvfb.log 2>&1 &
xvfb_pid=$!
cleanup_xvfb() {
    kill "$xvfb_pid" 2>/dev/null || true
    wait "$xvfb_pid" 2>/dev/null || true
}
trap cleanup_xvfb EXIT INT TERM
ready=0
for attempt in $(seq 1 100); do
    if DISPLAY=:99 xdpyinfo >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.1
done
if [ "$ready" -ne 1 ]; then
    cat /tmp/xvfb.log >&2
    echo 'Xvfb did not become ready' >&2
    exit 1
fi
DISPLAY=:99 dbus-run-session -- ctest --test-dir obj-x86_64-linux-gnu \
    -j1 --output-on-failure \
    -R '^(kwin-testWindowPaintData|kwin-testColorspaces|kwin-testMockDrm)$'
cleanup_xvfb
trap - EXIT INT TERM

# Tests have already passed in the configured tree. nocheck prevents Debian's
# default parallel, hardware-unaware test invocation from running them again.
DEB_BUILD_OPTIONS=nocheck dpkg-buildpackage --build=binary --no-sign -nc
cp /build/*.deb /out/
"""
    run([
        "docker", "run", "--rm", "--network=host",
        "-e", "CI=1",
        "-e", f"SOURCE_BASENAME={source.name}",
        "-e", f"LOCAL_VERSION={local_version}",
        "--device", f"{vkms_node}:/dev/dri/card1",
        "-v", f"{source.parent}:/build",
        "-v", f"{output}:/out",
        "-v", f"{NEON_SOURCES}:/host/neon.sources:ro",
        "-v", f"{NEON_KEY}:/host/neon-archive-keyring.asc:ro",
        image, "/bin/sh", "-c", script,
    ])


def validate_packages(output: Path, local_version: str) -> None:
    debs = list(output.glob("*.deb"))
    if not debs:
        raise MonitorError("build produced no Debian packages")
    names: set[str] = set()
    for deb in debs:
        name = run(["dpkg-deb", "-f", str(deb), "Package"], capture=True).strip()
        version = run(["dpkg-deb", "-f", str(deb), "Version"], capture=True).strip()
        names.add(name)
        if version != local_version:
            raise MonitorError(f"{deb.name} has unexpected version {version}")
    missing = {"kwin-wayland", "kwin-common"} - names
    if missing:
        raise MonitorError(f"build missing required packages: {', '.join(sorted(missing))}")


def enable_local_repository(source_file: Path = LOCAL_SOURCE) -> None:
    try:
        content = source_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise MonitorError(f"cannot read local APT source: {exc}") from exc
    if "Enabled: yes" in content:
        return
    if "Enabled: no" not in content:
        raise MonitorError("local APT source has no managed Enabled field")
    updated = content.replace("Enabled: no", "Enabled: yes", 1)
    try:
        source_file.write_text(updated, encoding="utf-8")
    except OSError as exc:
        raise MonitorError(f"cannot enable local APT source: {exc}") from exc


def publish(output: Path, version: str, config: dict[str, str]) -> None:
    builds = STATE / "builds"
    builds.mkdir(parents=True, exist_ok=True)
    destination = builds / version.replace(":", "_")
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(output, destination)

    keep = int(config.get("KEEP_SUCCESSFUL_BUILDS", "2"))
    retained = sorted((path for path in builds.iterdir() if path.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[:keep]
    for stale in set(builds.iterdir()) - set(retained):
        if stale.is_dir():
            shutil.rmtree(stale)

    repository_root = STATE / "repository"
    repository_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="staging-", dir=repository_root))
    pool = staging / "pool" / "main"
    binary = staging / "dists" / "stable" / "main" / "binary-amd64"
    pool.mkdir(parents=True)
    binary.mkdir(parents=True)
    for build in retained:
        for deb in build.glob("*.deb"):
            shutil.copy2(deb, pool / deb.name)
    packages = run(["dpkg-scanpackages", "--multiversion", "pool/main"], cwd=staging, capture=True)
    (binary / "Packages").write_text(packages, encoding="utf-8")
    run(["gzip", "-9", "-k", str(binary / "Packages")])
    release = run([
        "apt-ftparchive", "-o", "APT::FTPArchive::Release::Origin=KWin CTM Monitor",
        "-o", "APT::FTPArchive::Release::Label=KWin CTM Monitor",
        "-o", "APT::FTPArchive::Release::Suite=stable",
        "release", str(staging / "dists" / "stable"),
    ], capture=True)
    release_path = staging / "dists" / "stable" / "Release"
    release_path.write_text(release, encoding="utf-8")
    gnupg = STATE / "gnupg"
    run(["gpg", "--homedir", str(gnupg), "--batch", "--yes", "--armor", "--detach-sign", "-o", str(release_path) + ".gpg", str(release_path)])
    run(["gpg", "--homedir", str(gnupg), "--batch", "--yes", "--clearsign", "-o", str(release_path.parent / "InRelease"), str(release_path)])

    link = repository_root / "current"
    temporary_link = repository_root / ".current-new"
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(staging.name)
    os.replace(temporary_link, link)
    for old in repository_root.glob("staging-*"):
        if old != staging and not (link.is_symlink() and link.resolve() == old.resolve()):
            shutil.rmtree(old)
    enable_local_repository()


def build() -> None:
    if os.geteuid() != 0:
        raise MonitorError("build must run as root")
    config = load_config()
    with exclusive_lock():
        version = versions_from_madison()[-1]
        if already_published(version):
            enable_local_repository()
            write_status("published", neon_version=version, message="already current")
            return
        write_status("building", neon_version=version)
        CACHE.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="build-", dir=CACHE) as temporary:
            work = Path(temporary)
            source = prepare_source(work, version)
            output = work / "packages"
            local_version = f"{version}+ctm1"
            vkms_node = find_vkms_node()
            build_in_docker(source, output, config.get("BUILD_IMAGE", "ubuntu:24.04"), vkms_node, local_version)
            validate_packages(output, local_version)
            publish(output, local_version, config)
        write_status("published", neon_version=version, local_version=local_version)


def show_status() -> int:
    if not STATUS.exists():
        print("KWin CTM monitor has not completed a check.")
        return 1
    print(STATUS.read_text(encoding="utf-8"), end="")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="kwin-ctm-monitor")
    parser.add_argument("command", choices=("status", "check", "build"))
    args = parser.parse_args()
    try:
        if args.command == "status":
            return show_status()
        version = versions_from_madison()[-1]
        if args.command == "check":
            print(json.dumps({"neon_version": version, "published": already_published(version)}, indent=2))
            return 0
        build()
        return 0
    except MonitorError as exc:
        if os.geteuid() == 0:
            write_status("failed", error=str(exc))
        print(f"kwin-ctm-monitor: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
