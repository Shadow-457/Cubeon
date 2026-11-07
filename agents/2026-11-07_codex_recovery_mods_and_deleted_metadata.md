# Recovery mods and deleted instance metadata

Published `/docs#guide-recovery-mods` in `6b99ba01 [skip ci]`, with all 25
Cubeon Client JARs pinned to existing stable v1.4.0 and official version-list
links for dependencies/performance mods. Uploaded the JARs without replacing
any installer. Downloaded every public JAR and verified size/SHA-256; all four
live Docs pages and shared CSS match source. Browser checks cover desktop,
mobile, Arabic, search, keyboard accordions and downloads without JavaScript.
Refreshed catalogues and restored Arabic translations for current stable copy.

Deleted/corrupt registered metadata now leaves the instance visible and Play
blocked instead of aborting startup. Folder organization and content paths
remain strict; read-only catalogues can skip damaged instances. Tested deletion,
malformed/wrong metadata, cache invalidation/restoration, missing runtime files,
healthy profiles and active-path validation. The real headless launcher passed
startup, blocked Play, instance switching and Settings with deleted metadata.
Passed 46 storage, 272 UI, 75 version UI, 20 install-flow, 40 instance, 17 scan
cache, 14 version resolver, six translation and 11 SEO checks. No new launcher
binary release or manual Windows reproduction. The icon report still has no
reproduction steps. Preserved concurrent Cubeon Bench edits.
