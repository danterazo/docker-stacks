# LM Studio model path migration

## Completed: 2026-11-22

- On the NAS `kex`, `/tank/models/language-models/gguf` was renamed to
  `/tank/models/language-models/lm-studio_gguf`. The publisher/model
  subdirectory structure was preserved.
- On Marigold, LM Studio's `downloadsFolder` was changed to
  `Z:\models\language-models\lm-studio_gguf`. Its `Z:` drive was verified
  as `\\kex\tank`. The previous settings were backed up as
  `C:\Users\dante\.lmstudio\settings.json.bak-model-path-20261122-002616`.
- Marigold could read the new share, and `lms ls` listed 36 models after
  reindexing. The CLI started LM Studio in headless mode for verification;
  its HTTP server was stopped afterwards. The headless LM Studio process may
  remain running.
- vLLM still uses the separate `safetensors` directory and was not changed.

## Pending: Ovedur

Ovedur was offline during the migration. When it returns:

1. Verify which drive or UNC path points to `\\kex\tank` on Ovedur.
2. In LM Studio's **My Models** directory settings, replace the old
   `models\language-models\gguf` location with
   `models\language-models\lm-studio_gguf` on that same share. Do not assume
   Ovedur uses Marigold's `Z:` mapping.
3. Refresh or restart LM Studio and check the model list (`lms ls`); if needed,
   check that the new shared path is readable. Do not delete model-index or
   metadata caches merely to force a refresh.
4. Update other Ovedur scripts or shortcuts that reference the old path, after
   inspecting them. Record completion here.

The legacy path was not retained as a symlink. SMB clients may briefly cache
the old name after the server-side rename.
