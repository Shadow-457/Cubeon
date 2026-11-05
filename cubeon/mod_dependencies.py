"""Resolve declared mod dependencies and version conflicts before Play.

Clean profiles stay local. Repairs stage and verify the complete compatible set
before reversible publication, retaining enabled identities and original JARs.
"""
import os
import time

from . import global_mod_cache, mods, net

MAX_REPAIRS = 16
REPAIR_SECONDS = 60


def _scan(mc_version, loader, version_id):
    directory = mods.resolve_profile_dir(mc_version, loader, version_id)
    entries = []
    for item in mods.list_mods(mc_version, loader, version_id):
        meta, provided = mods._doctor_metadata(
            os.path.join(directory, item["filename"]), loader)
        entries.append((item, meta, provided))
    return entries


def _stage(candidate, folder, timeout, deadline):
    from .modpacks import _host_allowed
    name = mods._safe_download_filename(candidate["filename"])
    if not _host_allowed(candidate.get("url") or ""):
        raise ValueError("The dependency download host is not trusted")
    destination = os.path.join(folder, name)
    hashes = candidate.get("hashes") or {}
    expected = next(((algo, hashes[algo]) for algo in ("sha512", "sha256", "sha1")
                     if hashes.get(algo)), None)

    def progress(*args):
        if time.monotonic() >= deadline:
            raise net.DownloadError("Dependency repair time limit reached; retry Play")

    def fetch(path):
        net.download_to(path, candidate["url"], headers=mods.modrinth_headers(),
                        timeout=timeout, attempts=mods.LAUNCH_LOOKUP_ATTEMPTS,
                        expected_hash=expected, progress_cb=progress, deadline=deadline)

    global_mod_cache.get_or_fetch(destination, fetch, hashes)
    return destination


def run_dependency_doctor(mc_version, loader, *, version_id=None, status_cb=None,
                          check_online=True, auto_fix=True, runtime_versions=None):
    """Verify and repair required dependencies and conflicts before staging/spawn.

    A clean profile is local-only. Repairs retain enabled mod identities, verify
    actual JARs, and commit the complete compatible set with rollback/backups.
    """
    result = {"checked": 0, "fixed": [], "unfixed": []}
    if not mc_version or loader not in ("fabric", "quilt", "forge", "neoforge"):
        return result
    from .mod_resolver import Resolver
    runtime = mods._doctor_runtime_versions(mc_version, loader, version_id)
    runtime.update({key: str(value) if value is not None else None
                    for key, value in (runtime_versions or {}).items()})
    directory = mods.get_profile_dir(mc_version, loader, version_id)
    snapshot = mods._doctor_profile_snapshot(directory)
    entries = _scan(mc_version, loader, version_id)
    resolver = Resolver(entries, runtime, mc_version, loader, version_id,
                        time.monotonic() + REPAIR_SECONDS, MAX_REPAIRS,
                        check_online, _stage, _scan, status_cb, snapshot=snapshot)
    result = resolver.run(auto_fix)
    if result["fixed"] or result["unfixed"]:
        import logging
        from .atomicio import write_json
        log = logging.getLogger(__name__)
        for entry in result["unfixed"]:
            log.warning("Automatic Doctor: %s. %s", entry["detail"], entry["error"])
        for entry in result["fixed"]:
            log.info("Automatic Doctor: %s: %s", entry["dependency"], entry["fix"])
        try:
            write_json(os.path.join(resolver.directory, ".cubeon-auto-doctor.json"),
                       dict(result, mc_version=mc_version, loader=loader, version_id=version_id))
        except OSError:
            log.warning("Could not save the automatic Doctor report", exc_info=True)
    return result
