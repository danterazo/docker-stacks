#!/usr/bin/env python3
import bz2
import hashlib
import importlib.util
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "dawarich/update-photon.py"
SPEC = importlib.util.spec_from_file_location("photon_update", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
PHOTON = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PHOTON)


class PhotonUpdateTests(unittest.TestCase):
    def test_selects_latest_complete_stable_release_not_alias_or_master(self):
        names = [
            "photon-db-planet-release-261101.tar.bz2",
            "photon-db-planet-release-261115.tar.bz2",
            "photon-db-planet-release-261122.tar.bz2",
            "photon-db-planet-1.0-latest.tar.bz2",
            "photon-db-planet-master-261125.tar.bz2",
            "photon-db-planet-0.7-latest.tar.bz2",
        ]
        listing = "".join(f'<a href="{name}">{name}</a>' for name in names)
        listing += "".join(f'<a href="{name}.md5">checksum</a>' for name in names if "261122" not in name)
        self.assertEqual(PHOTON.select_release(listing=listing), names[1])
        with self.assertRaisesRegex(ValueError, "no dated stable"):
            PHOTON.select_release(listing='<a href="photon-db-planet-1.0-latest.tar.bz2">alias</a>')

    def test_rejects_mismatched_checksum_and_corrupt_archive(self):
        name = "photon-db-planet-release-261115.tar.bz2"
        digest = hashlib.md5(b"original").hexdigest()
        self.assertEqual(PHOTON.parse_checksum(text=digest + "  " + name, filename=name), digest)
        with self.assertRaisesRegex(ValueError, "different archive"):
            PHOTON.parse_checksum(text=digest + "  other.tar.bz2", filename=name)
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / name
            archive.write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "MD5 mismatch"):
                PHOTON.verify_archive(path=archive, checksum=digest)

    def extract(self, *, name="photon_data/node_1/test.bin", kind=tarfile.REGTYPE, corrupt=False):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            member = tarfile.TarInfo(name)
            member.type = kind
            member.linkname = "../../outside"
            data = b"index fixture" * 1000
            if kind == tarfile.REGTYPE:
                member.size = len(data)
            archive.addfile(member, io.BytesIO(data) if member.isfile() else None)
        data = buffer.getvalue()
        compressed = bz2.compress(data[:1024]) + bz2.compress(data[1024:])
        if corrupt:
            compressed = compressed[:-10]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "extract"
            target.mkdir()
            result = subprocess.run(
                [sys.executable, "-c", PHOTON.EXTRACTOR, str(target), shutil.which("bzip2"), "-dc"],
                input=compressed,
                capture_output=True,
                check=False,
            )
            contents = (target / "photon_data/node_1/test.bin").read_bytes() if (target / "photon_data/node_1/test.bin").is_file() else None
            self.assertFalse((Path(directory) / "outside").exists())
            return result, contents

    def test_extracts_concatenated_bzip2_streams(self):
        result, contents = self.extract()
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertEqual(contents, b"index fixture" * 1000)

    def test_rejects_traversal_absolute_paths_and_links(self):
        for name, kind in [
            ("../outside", tarfile.REGTYPE),
            ("/outside", tarfile.REGTYPE),
            ("photon_data/../../outside", tarfile.REGTYPE),
            ("photon_data/node_1/link", tarfile.SYMTYPE),
            ("photon_data/node_1/link", tarfile.LNKTYPE),
        ]:
            with self.subTest(name=name, kind=kind):
                result, _ = self.extract(name=name, kind=kind)
                self.assertNotEqual(result.returncode, 0)

    def test_rejects_corruption_after_tar_payload(self):
        result, _ = self.extract(corrupt=True)
        self.assertNotEqual(result.returncode, 0)

    def test_reuses_only_completed_matching_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / "photon-db-planet-release-261115.tar.bz2"
            archive.write_bytes(b"fixture")
            release = root / "releases" / archive.name.removesuffix(".tar.bz2")
            (release / "photon_data/node_1").mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "completion marker"):
                PHOTON.stage_release(root=root, archive=archive, checksum="fixture", image="fixture")
            (release / ".release.json").write_text(json.dumps({"archive": archive.name, "md5": "fixture"}))
            with mock.patch.object(PHOTON.subprocess, "run") as command:
                self.assertEqual(PHOTON.stage_release(root=root, archive=archive, checksum="fixture", image="fixture"), release)
                command.assert_not_called()

    def test_selected_but_unhealthy_release_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "releases/photon-db-planet-release-261115"
            release.mkdir(parents=True)
            (root / "current").symlink_to("releases/" + release.name)
            with mock.patch.object(PHOTON, "capture", return_value=""), mock.patch.object(PHOTON.subprocess, "run") as command:
                PHOTON.activate_release(root=root, release=release)
                calls = [call.args[0] for call in command.call_args_list]
                self.assertTrue(any("up" in call and call[-1] == "dawarich-geo" and "--no-deps" in call for call in calls))
                self.assertFalse(any("dawarich-app" in call or "dawarich-db" in call for call in calls))


if __name__ == "__main__":
    unittest.main()
