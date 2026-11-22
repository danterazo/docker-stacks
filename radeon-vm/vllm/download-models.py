#!/usr/bin/env python3
"""Download or quickly verify the selected public Hugging Face checkpoints."""

# Add model IDs here. Append @<commit> to pin a specific revision; without it,
# the current main branch is used. Hugging Face model URLs are also accepted.
MODELS = [
	'btbtyler09/Qwen3.8-27B-GPTQ-4bit@b64f44dfedb71b73287219e0ec348b0a20c447e2',
	'google/gemma-4-31B-it-qat-w4a16-ct@52f3f65bc7a02d555763bc923bd1d9094898219d',
	'ibm-granite/granite-4.2-30b@9e668ce1c538387ef24d3644e9b0606647762636',
	'microsoft/Phi-4-reasoning-plus@69baf8528e1bcf05f475034d9e5dd32875ed125f',
]

import fcntl
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path, PurePosixPath

DISK = Path(os.environ.get('VLLM_MODEL_DISK', '/models'))
IMAGE = 'blivioniag/vllm-rdna:v0.31.0-extras'
REPO_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$')
REV_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]*$')


def parse_model(value):
	value = value.removeprefix('https://huggingface.co/').rstrip('/')
	repo, separator, revision = value.partition('@')
	if not REPO_RE.fullmatch(repo) or (separator and not REV_RE.fullmatch(revision)):
		raise ValueError(f'Invalid model entry: {value}')
	return repo, revision if separator else 'main'


def model_info(repo, revision):
	url = f'https://huggingface.co/api/models/{repo}/revision/{revision}?blobs=true'
	request = urllib.request.Request(url, headers={'User-Agent': 'radeon-vm-model-manager'})
	with urllib.request.urlopen(request, timeout=30) as response:
		info = json.load(response)
	sha = info.get('sha', '')
	if not re.fullmatch(r'[0-9a-f]{40}', sha):
		raise ValueError(f'Invalid resolved revision for {repo}')
	files = []
	for item in info.get('siblings', []):
		name = item['rfilename']
		path = PurePosixPath(name)
		if path.is_absolute() or any(part in ('', '.', '..') for part in name.split('/')):
			raise ValueError(f'Unsafe model file path: {name}')
		size = item.get('size')
		etag = item.get('lfs', {}).get('sha256') or item.get('blobId')
		if not isinstance(size, int) or size < 0 or not etag:
			raise ValueError(f'Missing file metadata for {name}')
		files.append((name, size, etag))
	if not files:
		raise ValueError(f'No files returned for {repo}')
	return sha, files


def verify(target, sha, files):
	"""Check every expected file's size and download metadata, not content hashes."""
	if target.is_symlink() or not target.is_dir():
		return False
	for name, size, etag in files:
		path = target / name
		meta = target / '.cache/huggingface/download' / (name + '.metadata')
		try:
			if (not path.resolve().is_relative_to(target.resolve())
					or not meta.resolve().is_relative_to(target.resolve())
					or not path.is_file() or path.is_symlink() or path.stat().st_size != size):
				return False
			lines = meta.read_text().splitlines()
			if len(lines) < 2 or lines[0] != sha or lines[1].strip('"') != etag:
				return False
		except (OSError, UnicodeError):
			return False
	return True


def download(root, repo, sha, partial):
	container_dir = '/models/' + partial.relative_to(root).as_posix()
	code = ('import sys; from huggingface_hub import snapshot_download; '
		'snapshot_download(repo_id=sys.argv[1], revision=sys.argv[2], local_dir=sys.argv[3])')
	subprocess.run([
		'docker', 'run', '--rm', '--user', f'{os.getuid()}:{os.getgid()}',
		'--env', 'HOME=/tmp', '--env', 'HF_HOME=/tmp/huggingface',
		'--mount', f'type=bind,source={root},target=/models',
		'--entrypoint', 'python', IMAGE, '-c', code, repo, sha, container_dir,
	], check=True)


def manage(root, entries):
	root = root.resolve()
	for entry in entries:
		repo, revision = parse_model(entry)
		sha, files = model_info(repo, revision)
		target = root / 'language-models/hf_safetensors' / repo
		partial = root / '.model-downloads' / repo / sha
		# Do not follow a pre-existing directory symlink outside the model disk.
		if not target.resolve().is_relative_to(root) or not partial.resolve().is_relative_to(root):
			raise ValueError(f'Model path escapes the model disk: {repo}')
		if target.exists() or target.is_symlink():
			if not verify(target, sha, files):
				raise ValueError(f'Existing checkpoint is incomplete or differs: {target}; left untouched')
			print(f'Verified {repo}@{sha} (metadata and sizes; no full rehash)', flush=True)
			continue
		partial.parent.mkdir(parents=True, exist_ok=True)
		target.parent.mkdir(parents=True, exist_ok=True)
		print(f'Downloading {repo}@{sha}', flush=True)
		download(root, repo, sha, partial)
		if not verify(partial, sha, files):
			raise ValueError(f'Download verification failed: {partial}; retained for inspection')
		if target.exists() or target.is_symlink():
			raise ValueError(f'Destination appeared during download: {target}; partial retained')
		partial.rename(target)
		print(f'Installed {repo}@{sha} at {target}', flush=True)


def main():
	if not DISK.is_absolute() or not os.path.ismount(DISK):
		raise ValueError(f'Model disk is not mounted at an absolute path: {DISK}')
	root = DISK / 'vllm'
	if not root.is_dir() or root.is_symlink():
		raise ValueError(f'Local vLLM model directory is unavailable: {root}')
	with (root / '.model-downloads.lock').open('a') as lock:
		fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
		manage(root, MODELS)


if __name__ == '__main__':
	try:
		main()
	except (OSError, ValueError, subprocess.CalledProcessError) as error:
		print(f'Model manager: {error}', file=sys.stderr)
		sys.exit(1)
