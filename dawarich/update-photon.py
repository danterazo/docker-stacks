#!/usr/bin/env python3
"""download, verify & install the stable Photon planet index on the owning PVE node."""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

BASE_URL = "https://download1.graphhopper.com/public/"
RELEASE = re.compile(r"photon-db-planet-release-(\d{6})\.tar\.bz2")
CTID = "118"
GUEST_DATA = "/docker/dawarich/data/photon"
CACHE = Path("/tank/downloads/photon-db")
COMPOSE = ["docker", "compose", "--project-directory", "/docker/dawarich", "--profile", "geocoding"]

# run inside the existing Photon image: its lbzip2 supports concatenated streams.
EXTRACTOR = r"""
import pathlib
import shutil
import subprocess
import sys
import tarfile

target = pathlib.Path(sys.argv[1]).resolve(strict=True)
process = subprocess.Popen(sys.argv[2:], stdin=sys.stdin.buffer, stdout=subprocess.PIPE)
total = 0
reported = 0
try:
	with tarfile.open(fileobj=process.stdout, mode='r|') as archive:
		for member in archive:
			path = pathlib.PurePosixPath(member.name)
			if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0] != 'photon_data':
				raise ValueError('unsafe archive path: ' + member.name)
			if not (member.isdir() or member.isfile()):
				raise ValueError('unsupported archive member: ' + member.name)
			archive.extract(member, path=target, filter='data')
			total += member.size
			if total - reported >= 10_000_000_000:
				print(f'extracted {total / 1e9:.1f} GB', flush=True)
				reported = total
	# consume padding too, checking every compressed stream and its CRC.
	while process.stdout.read(1024 * 1024):
		pass
	if process.wait() != 0:
		raise RuntimeError('decompression failed')
	if not (target / 'photon_data/node_1').is_dir() or total == 0:
		raise ValueError('archive does not contain a populated Photon index')
	print(f'extracted {total / 1e9:.1f} GB; archive complete', flush=True)
finally:
	process.stdout.close()
	if process.poll() is None:
		process.terminate()
	process.wait()
"""


def read_url(*, url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read().decode("utf-8")


def select_release(*, listing: str) -> str:
    names = set(re.findall(r'href=["\']([^"\']+)["\']', listing))
    releases = []
    for name in names:
        match = RELEASE.fullmatch(name)
        if match and name + ".md5" in names:
            date = datetime.datetime.strptime(match.group(1), "%y%m%d").date()
            releases.append((date, name))
    if not releases:
        raise ValueError("no dated stable planet release with a checksum in the official index")
    return max(releases)[1]


def parse_checksum(*, text: str, filename: str) -> str:
    parts = text.strip().split()
    if not parts or not re.fullmatch(r"[0-9a-fA-F]{32}", parts[0]):
        raise ValueError("invalid upstream MD5 checksum")
    if len(parts) > 2 or (len(parts) == 2 and parts[1].lstrip("*") != filename):
        raise ValueError("checksum names a different archive")
    return parts[0].lower()


def verify_archive(*, path: Path, checksum: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular archive: {path}")
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "md5").hexdigest()
    if actual != checksum:
        raise ValueError(f"MD5 mismatch: {path}; existing data was not replaced")


@contextmanager
def data_owner() -> Iterator[None]:
    if os.geteuid() == 1000:
        yield
        return
    groups = os.getgroups()
    group = os.getegid()
    os.setgroups([])
    os.setegid(1000)
    os.seteuid(1000)
    try:
        yield
    finally:
        os.seteuid(0)
        os.setegid(group)
        os.setgroups(groups)


def capture(*, command: list[str]) -> str:
    return subprocess.check_output(command, text=True).strip()


def guest(*command: str) -> list[str]:
    return ["pct", "exec", CTID, "--keep-env", "0", "--", "runuser", "-u", "dante", "--", *command]


def data_path(*, config: dict[str, object]) -> Path:
    if config.get("hostname") != "dawarich" or config.get("unprivileged") != 1:
        raise ValueError("LXC 118 is not the expected unprivileged Dawarich guest")
    mounts = []
    for key, value in config.items():
        if re.fullmatch(r"mp\d+", key) and isinstance(value, str):
            volume, *options = value.split(",")
            if f"mp={GUEST_DATA}" in options:
                if not {"backup=0", "replicate=0", "idmap=passthrough"}.issubset(options):
                    raise ValueError("Photon mount must exclude backups/replication and use idmap=passthrough")
                if volume != f"rpool-lxc:subvol-{CTID}-photon":
                    raise ValueError("unexpected Photon volume")
                mounts.append(volume)
    if len(mounts) != 1:
        raise ValueError("expected one active Photon mount; run on the current owning node")
    path = Path(capture(command=["pvesm", "path", mounts[0]]))
    if path.is_symlink() or not path.is_mount():
        raise ValueError(f"Photon dataset is not mounted: {path}")
    source = capture(command=["findmnt", "-n", "-o", "SOURCE", "--mountpoint", str(path)])
    if source != f"rpool/data/lxc/subvol-{CTID}-photon":
        raise ValueError("Photon mount has an unexpected filesystem")
    return path


def cached_archive(*, filename: str, checksum: str, cache: Path) -> Path:
    with data_owner():
        if not cache.is_absolute() or cache.is_symlink() or not cache.parent.is_mount() or cache.parent == Path("/"):
            raise ValueError(f"prepare a durable mounted cache parent on this node first: {cache.parent}")
        cache.mkdir(exist_ok=True)
        archive = cache / filename
        partial = cache / (filename + ".part")
        if partial.is_symlink() or archive.is_symlink():
            raise ValueError("refusing a symlink in the download cache")
        download = not archive.exists()
        if download and shutil.disk_usage(cache).free + (partial.stat().st_size if partial.exists() else 0) < 80_000_000_000:
            raise ValueError("less than 80 GB available for the download cache")
    if download:
        subprocess.run(
            [
                "runuser",
                "-u",
                "dante",
                "--",
                "aria2c",
                "--continue=true",
                "--auto-file-renaming=false",
                "--allow-overwrite=false",
                "--max-connection-per-server=2",
                "--split=2",
                "--min-split-size=64M",
                "--file-allocation=none",
                "--max-tries=5",
                "--retry-wait=10",
                "--summary-interval=60",
                "--console-log-level=warn",
                f"--checksum=md5={checksum}",
                f"--dir={cache}",
                f"--out={partial.name}",
                BASE_URL + filename,
            ],
            check=True,
        )
    with data_owner():
        if download:
            verify_archive(path=partial, checksum=checksum)
            partial.rename(archive)
        else:
            print(f"verifying cached archive: {archive}", flush=True)
            verify_archive(path=archive, checksum=checksum)
        metadata = cache / (filename + ".md5.new")
        with metadata.open("x") as output:
            output.write(f"{checksum}  {filename}\n")
        metadata.replace(cache / (filename + ".md5"))
    return archive


def stage_release(*, root: Path, archive: Path, checksum: str, image: str) -> Path:
    with data_owner():
        releases = root / "releases"
        if releases.is_symlink():
            raise ValueError("releases directory must not be a symlink")
        releases.mkdir(exist_ok=True)
        name = archive.name.removesuffix(".tar.bz2")
        destination = releases / name
        marker = destination / ".release.json"
        if destination.is_symlink() or marker.is_symlink():
            raise ValueError("release directory and marker must not be symlinks")
        if destination.exists():
            if not marker.is_file() or json.loads(marker.read_text()) != {"archive": archive.name, "md5": checksum}:
                raise ValueError(f"existing release has no matching completion marker: {destination}")
            if not (destination / "photon_data/node_1").is_dir():
                raise ValueError(f"completed release is missing its index: {destination}")
            return destination
        if shutil.disk_usage(root).free < archive.stat().st_size * 6:
            raise ValueError("insufficient Photon space for a staged planet index; retain the current index and review old releases")
        partial = releases / ("." + name + ".partial")
        partial.mkdir()
    command = guest(
        "docker",
        "run",
        "--rm",
        "-i",
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "1000:1000",
        "--mount",
        f"type=bind,src={GUEST_DATA}/releases/{partial.name},dst=/extract",
        "--entrypoint",
        "python3",
        image,
        "-c",
        EXTRACTOR,
        "/extract",
        "lbzip2",
        "-n4",
        "-dc",
    )
    print(f"extracting into {partial}; the active index is untouched", flush=True)
    with data_owner():
        source = os.fdopen(os.open(archive, os.O_RDONLY | os.O_NOFOLLOW), "rb")
    with source:
        subprocess.run(command, stdin=source, check=True)
    with data_owner():
        completion = partial / ".release.json"
        with completion.open("x") as output:
            output.write(json.dumps({"archive": archive.name, "md5": checksum}) + "\n")
        partial.rename(destination)
    return destination


def activate_release(*, root: Path, release: Path) -> None:
    with data_owner():
        current = root / "current"
        selected = False
        if current.is_symlink():
            target = os.readlink(current)
            if not re.fullmatch(r"releases/photon-db-planet-release-\d{6}", target):
                raise ValueError("unexpected current index link; refusing to replace it")
            if not current.is_dir():
                raise ValueError("current index link is broken; review before activation")
            selected = current.resolve() == release
        elif current.exists():
            raise ValueError("current must be a managed symlink, not an existing data directory")
    query = (
        "import json, urllib.request; "
        'r = json.load(urllib.request.urlopen("http://127.0.0.1:2322/reverse?lat=52.52&lon=13.405&limit=1", timeout=60)); '
        'assert r.get("features"), "reverse geocoding returned no features"; '
        'print("Photon reverse geocoding verified")'
    )
    healthy = capture(command=guest("docker", "ps", "--filter", "name=^/dawarich-geo$", "--filter", "health=healthy", "--format", "{{.Names}}"))
    if selected and healthy:
        subprocess.run(guest("docker", "exec", "dawarich-geo", "python3", "-c", query), check=True)
        print("latest Photon release is already selected and healthy; no restart needed", flush=True)
        return
    running = capture(command=guest("docker", "ps", "--filter", "name=^/dawarich-geo$", "--format", "{{.Names}}"))
    if running:
        print("stopping only Photon for index cutover; Dawarich and its database stay running", flush=True)
        subprocess.run(guest(*COMPOSE, "stop", "-t", "120", "dawarich-geo"), check=True)
    with data_owner():
        if not selected:
            link = root / ".current-new"
            link.symlink_to(Path("releases") / release.name)
            os.replace(link, current)
    print(f"selected {release.name}; previous releases are retained", flush=True)
    subprocess.run(
        guest(
            *COMPOSE, "up", "--no-deps", "--pull", "never", "--no-build", "--force-recreate", "-d", "--wait", "--wait-timeout", "900", "dawarich-geo"
        ),
        check=True,
    )
    subprocess.run(guest("docker", "exec", "dawarich-geo", "python3", "-c", query), check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="report the latest release without changing anything")
    mode.add_argument("--download-only", action="store_true", help="fill the durable cache without touching the guest")
    parser.add_argument("--cache-dir", type=Path, default=CACHE, help="existing durable download parent required")
    args = parser.parse_args()
    filename = select_release(listing=read_url(url=BASE_URL))
    checksum = parse_checksum(text=read_url(url=BASE_URL + filename + ".md5"), filename=filename)
    print(f"latest stable Photon planet release: {filename} (MD5 {checksum})", flush=True)
    if args.check:
        return
    if os.geteuid() != 0 or socket.gethostname().split(".")[0] not in {"kex", "cerulean"}:
        raise ValueError("run on the owning PVE node as root; --check is safe on the local workstation")
    descriptor = os.open("/run/lock/dawarich-photon-update.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        info = os.fstat(lock.fileno())
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("unexpected update lock ownership or type")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        root = None
        if not args.download_only:
            node = socket.gethostname().split(".")[0]
            config = json.loads(capture(command=["pvesh", "get", f"/nodes/{node}/lxc/{CTID}/config", "--current", "1", "--output-format", "json"]))
            root = data_path(config=config)
        archive = cached_archive(filename=filename, checksum=checksum, cache=args.cache_dir)
        print(f"verified durable archive: {archive}", flush=True)
        if root is None:
            return
        model = json.loads(capture(command=guest(*COMPOSE, "config", "--no-env-resolution", "--format", "json", "dawarich-geo")))
        service = model["services"]["dawarich-geo"]
        image = service["image"]
        expected_mount = [
            mount
            for mount in service.get("volumes", [])
            if mount.get("type") == "bind"
            and mount.get("source", "").rstrip("/") == GUEST_DATA + "/current"
            and mount.get("target", "").rstrip("/") == "/photon/data"
            and mount.get("bind", {}).get("create_host_path") is False
        ]
        if (
            not re.fullmatch(r"rtuszik/photon-docker:[\w.-]+", image)
            or service.get("user") != "1000:1000"
            or service.get("environment", {}).get("UPDATE_STRATEGY") != "DISABLED"
            or len(expected_mount) != 1
        ):
            raise ValueError("publish the managed-current, non-root Photon Compose configuration before updating")
        if not capture(command=guest("docker", "image", "ls", image, "--format", "{{.ID}}")):
            subprocess.run(guest("docker", "pull", image), check=True)
        release = stage_release(root=root, archive=archive, checksum=checksum, image=image)
        activate_release(root=root, release=release)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, urllib.error.URLError) as error:
        print(f"Photon update failed: {error}", file=sys.stderr)
        print("no automatic deletion or rollback was performed; inspect the reported cache/staging paths before retrying", file=sys.stderr)
        sys.exit(1)
