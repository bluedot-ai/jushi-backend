import os
import tempfile
import unittest
from pathlib import Path

from backend.modules.system.algorithm_version import get_algorithm_version


class AlgorithmVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def _workdir(self, arch):
        directory = self.root / f"mtworkflow_{arch}"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def test_explicit_x86_reads_version_from_filename(self):
        (self._workdir("x86") / "version_1.0.41.4").touch()

        result = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="x86",
            machine="aarch64",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], "1.0.41.4")
        self.assertEqual(result["arch"], "x86")

    def test_auto_arch_reads_arm_directory(self):
        (self._workdir("arm") / "version_2.3.0").touch()

        result = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="auto",
            machine="aarch64",
        )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["version"], "2.3.0")
        self.assertEqual(result["arch"], "arm")

    def test_missing_version_file_returns_not_found(self):
        self._workdir("x86")

        result = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="x86",
            machine="x86_64",
        )

        self.assertEqual(result["status"], "not_found")
        self.assertIsNone(result["version"])

    def test_multiple_version_files_return_conflict(self):
        directory = self._workdir("arm")
        (directory / "version_1.0.0").touch()
        (directory / "version_1.0.1").touch()

        result = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="arm",
            machine="aarch64",
        )

        self.assertEqual(result["status"], "conflict")
        self.assertIsNone(result["version"])

    def test_invalid_names_and_directories_are_ignored(self):
        directory = self._workdir("x86")
        (directory / "version_").touch()
        (directory / "version_1.0.0+").touch()
        (directory / "version_9.9.9").mkdir()

        result = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="x86",
            machine="x86_64",
        )

        self.assertEqual(result["status"], "not_found")

    def test_missing_directory_and_unknown_arch_degrade_cleanly(self):
        unavailable = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="x86",
            machine="x86_64",
        )
        unsupported = get_algorithm_version(
            base_dir=os.fspath(self.root),
            configured_arch="auto",
            machine="mips64",
        )

        self.assertEqual(unavailable["status"], "unavailable")
        self.assertEqual(unsupported["status"], "unsupported_arch")


if __name__ == "__main__":
    unittest.main()

