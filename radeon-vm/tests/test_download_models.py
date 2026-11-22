#!/usr/bin/env python3
"""Exercise model selection and idempotent installs without large downloads."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / 'vllm/download-models.py'
spec = importlib.util.spec_from_file_location('download_models', SCRIPT)
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)
SHA = 'a' * 40
FILES = [('config.json', 4, 'etag1'), ('sub/weights', 5, 'etag2')]


def populate(directory):
	for name, size, etag in FILES:
		path = directory / name
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_bytes(b'x' * size)
		metadata = directory / '.cache/huggingface/download' / (name + '.metadata')
		metadata.parent.mkdir(parents=True, exist_ok=True)
		metadata.write_text(f'{SHA}\n{etag}\n0\n')


class ModelTests(unittest.TestCase):
	def setUp(self):
		self.temp = tempfile.TemporaryDirectory()
		self.addCleanup(self.temp.cleanup)
		self.root = Path(self.temp.name)

	def test_parse_names_and_urls(self):
		self.assertEqual(manager.parse_model('org/name'), ('org/name', 'main'))
		self.assertEqual(manager.parse_model('https://huggingface.co/org/name@abc'), ('org/name', 'abc'))
		for bad in ('../name', 'org/name@../bad', 'https://other.invalid/org/name'):
			with self.assertRaises(ValueError):
				manager.parse_model(bad)

	def test_download_and_repeat_without_download(self):
		def fake_download(root, repo, sha, partial):
			populate(partial)
		with mock.patch.object(manager, 'model_info', return_value=(SHA, FILES)), \
				mock.patch.object(manager, 'download', side_effect=fake_download) as download:
			manager.manage(self.root, ['org/one', 'org/two'])
			manager.manage(self.root, ['org/one', 'org/two'])
			self.assertEqual(download.call_count, 2)
		self.assertTrue((self.root / 'language-models/hf_safetensors/org/one/config.json').is_file())

	def test_direct_model_root_layout(self):
		def fake_download(root, repo, sha, partial):
			populate(partial)
		with mock.patch.object(manager, 'model_info', return_value=(SHA, FILES)), \
				mock.patch.object(manager, 'download', side_effect=fake_download) as download:
			manager.manage(self.root, ['org/one'], model_subdir=Path('.'))
			download.assert_called_once()
		self.assertTrue((self.root / 'org/one/config.json').is_file())

	def test_incomplete_existing_never_overwritten(self):
		target = self.root / 'language-models/hf_safetensors/org/one'
		populate(target)
		(target / 'config.json').write_text('wrong length')
		with mock.patch.object(manager, 'model_info', return_value=(SHA, FILES)), \
				mock.patch.object(manager, 'download') as download:
			with self.assertRaises(ValueError):
				manager.manage(self.root, ['org/one'])
			download.assert_not_called()
		self.assertEqual((target / 'config.json').read_text(), 'wrong length')

	def test_failed_download_keeps_partial(self):
		def broken_download(root, repo, sha, partial):
			partial.mkdir(parents=True)
			(partial / 'config.json').write_text('partial')
		with mock.patch.object(manager, 'model_info', return_value=(SHA, FILES)), \
				mock.patch.object(manager, 'download', side_effect=broken_download):
			with self.assertRaises(ValueError):
				manager.manage(self.root, ['org/one'])
		self.assertTrue((self.root / '.model-downloads/org/one' / SHA / 'config.json').exists())
		self.assertFalse((self.root / 'language-models/hf_safetensors/org/one').exists())

	def test_no_mount_is_rejected(self):
		with mock.patch.object(manager, 'DISK', self.root), \
				mock.patch('os.path.ismount', return_value=False):
			with self.assertRaises(ValueError):
				manager.main()

	def test_main_supports_a_mounted_direct_model_root(self):
		def fake_download(root, repo, sha, partial):
			populate(partial)
		with mock.patch.dict('os.environ', {'VLLM_MODEL_ROOT': str(self.root)}), \
				mock.patch('os.path.ismount', return_value=True), \
				mock.patch.object(manager, 'MODELS', ['org/one']), \
				mock.patch.object(manager, 'model_info', return_value=(SHA, FILES)), \
				mock.patch.object(manager, 'download', side_effect=fake_download):
			manager.main()
		self.assertTrue((self.root / 'org/one/config.json').is_file())


if __name__ == '__main__':
	unittest.main()
