[Documentation](../README.md) / Releases

# Release checklist

Use this alongside the [build guide](build.md). Publishing and testing are
separate jobs in the current workflow; review both results.

## Before the release

- [ ] Run `python tools/test_mega_smoke.py --suites` and review failures or skips.
- [ ] Run `node worker/test-worker.mjs` for Worker changes.
- [ ] Run the compile and version-matrix tests for mod changes, and rebuild
      affected jars before packaging.
- [ ] Update user-facing documentation for changed behavior.
- [ ] Review the intended version and channel with
      `python tools/release_version.py next`.
- [ ] Confirm whether the build includes Friends or uses the public build marker.
- [ ] Check that no credentials, identity files, or local diagnostic output
      are included in the patch or artifact.

## Desktop verification

Test the packaged build, not only `python main.py`. Record the operating
system, artifact, and results. Do not mark untested platforms as verified.

- [ ] Install or extract the app on a clean environment.
- [ ] Confirm the window opens and bundled images, fonts, and palettes load.
- [ ] Launch a game with the intended version, Java runtime, and loader.
- [ ] Switch installed instances and confirm their loader and content isolation.
- [ ] Check mods, modpacks, resource packs, and shader compatibility behavior.
- [ ] Check Cosmetics, screenshots in Settings, and Stats.
- [ ] Check navigation, text input, image stability, and resizing.
- [ ] If enabled, test Friends between separate sandbox identities.
- [ ] Check startup without network access and failure messages for unavailable
      downloads, missing Java, or insufficient disk space.
- [ ] Complete the [Windows smoke test](../WINDOWS_SMOKE_TEST.md) on real Windows
      hardware when shipping a Windows artifact.

## Publish

- [ ] Follow the repository's release workflow. A push to `main` can start it;
      do not create a second tag or release for the same version.
- [ ] Watch the build jobs and the asset-verification/publish job.
- [ ] Verify all six required assets exist before making a draft public.
- [ ] Keep beta versions as prereleases; they must not become the stable download.
- [ ] Deploy changed Workers using their own configuration and credentials.
      Packaging the launcher does not deploy them.
- [ ] Review generated release notes for useful, accurate descriptions.

## After publishing

- [ ] Test the public download page for each platform's asset.
- [ ] Confirm the stable and beta update feeds return the intended versions.
- [ ] Check that the running app offers the correct update and download page.
- [ ] Review reported startup or launch failures, with sensitive log data removed.

## Failed or defective releases

For a failed build, rerun the failed job and inspect the draft's assets.
The workflow reuses its version and tag on a rerun; do not mint a new version
solely to retry an upload.

For a shipped defect, normally publish a corrected newer version. Making
an older release latest does not downgrade installed applications. If
downloads must be rolled back, verify the download feed explicitly and
communicate the affected versions.

Do not delete a tag that has shipped to users. Check release-tooling tests
before changing version or channel behavior.
