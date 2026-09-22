# 2026-09-22 — explicit Slim handoff to CustomSkinLoader

CSL's `model: auto` chose wide arms for the live active skin because its spare
arm columns were opaque. Cubeon now persists the uploader's explicit model,
can apply it to an existing active skin, and writes `slim`/`default` into its
own LocalSkin CSL entry (including a queued ExtraList entry) before launch.
Verified by `tools/test_skin_preview.py`.
