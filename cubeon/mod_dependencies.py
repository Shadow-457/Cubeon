"""Repair the dependencies declared by installed Fabric/Quilt jars before Play.

Detection is local; only missing or outdated dependencies reach Modrinth.
Downloaded jars are staged and validated before replacing an enabled build.
The requester is never disabled, and old dependency builds are kept as backups.
"""
import os
import tempfile
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
        if meta:
            entries.append((item, meta, provided))
    return entries


def _providers(entries):
    provided = {}
    for item, meta, bundled in entries:
        if not item.get("enabled"):
            continue
        for identity, version in bundled.items():
            if identity not in provided or mods._cmp_versions(version, provided[identity]) > 0:
                provided[identity] = version
    return provided


def _requirements(entries, runtime):
    requirements = {}
    for item, meta, _ in entries:
        if not item.get("enabled"):
            continue
        for identity, predicate in (meta.get("depends") or {}).items():
            identity = str(identity).lower()
            if identity not in runtime:
                requirements.setdefault(identity, []).append((item, predicate))
    return requirements


def _missing(entries, runtime):
    providers = _providers(entries)
    return {identity: owners for identity, owners in _requirements(entries, runtime).items()
            if identity not in providers or not all(
                mods.version_satisfies(providers[identity], predicate)
                for _, predicate in owners)}


def _usable(meta, provided, identity, owners, entries, runtime, mc_version, loader):
    if not meta or identity not in provided or not all(
            mods.version_satisfies(provided[identity], predicate) for _, predicate in owners):
        return False
    if mods._doctor_local_incompatibility(meta, mc_version, loader):
        return False
    for key, predicate in (meta.get("depends") or {}).items():
        actual = runtime.get(key)
        if actual and not mods.version_satisfies(actual, predicate):
            return False
    # Replacing a dependency must not violate another requester's requirement
    # or introduce an explicit Fabric breaks conflict.
    candidate_id = str(meta.get("id") or "").lower()
    remaining = [entry for entry in entries if entry[0].get("enabled")
                 and str(entry[1].get("id") or "").lower() != candidate_id]
    providers = _providers(remaining)
    providers.update(provided)
    for key, constraints in _requirements(remaining, runtime).items():
        if key in provided and not all(mods.version_satisfies(provided[key], pred)
                                       for _, pred in constraints):
            return False
    for _, descriptor, _ in remaining + [({}, meta, provided)]:
        for key, predicate in (descriptor.get("breaks") or {}).items():
            if (descriptor is meta or key in provided) and key in providers \
                    and mods.version_satisfies(providers[key], predicate):
                return False
    return True


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


def _activate(path, candidate, identity, entries, mc_version, loader, version_id):
    """Swap only after validation; restore all renamed files if the swap fails."""
    directory = mods.get_profile_dir(mc_version, loader, version_id)
    filename = candidate["filename"]
    destination = os.path.join(directory, filename)
    candidate_meta = mods.read_mod_metadata(path, loader)
    candidate_id = str(candidate_meta.get("id") or "").lower()
    affected = [item for item, meta, _ in entries if item.get("enabled")
                and str(meta.get("id") or "").lower() == candidate_id]
    if any(item.get("protected") for item in affected):
        raise ValueError("A protected mod cannot be replaced automatically")
    # An unrelated file with the same name must never be overwritten.
    if os.path.lexists(destination) and filename not in {item["filename"] for item in affected}:
        raise ValueError("The dependency filename is already in use")
    moved = []
    landed = False
    try:
        for item in affected:
            source = os.path.join(directory, item["filename"])
            backup = source + ".disabled"
            suffix = 1
            while os.path.lexists(backup):
                backup = source + f".cubeon-previous-{suffix}"
                suffix += 1
            os.replace(source, backup)
            moved.append((source, backup))
        os.replace(path, destination)
        landed = True
        mods._write_meta(directory, filename, identity,
                         project_id=candidate.get("project_id") or identity,
                         url=candidate.get("url"))
    except BaseException:
        if landed:
            os.replace(destination, path)
        for source, backup in reversed(moved):
            os.replace(backup, source)
        raise


def run_dependency_doctor(mc_version, loader, *, version_id=None, status_cb=None,
                          check_online=True, auto_fix=True):
    """Non-interactive dependency repair, including profiles installed by old builds.

Only known unsatisfied jar requirements are repaired. Failed lookups are tried
once per dependency; a connection failure stops further network probes. A clean
profile does no network work. Unfixed requirements are returned to the caller.
"""
    result = {"checked": 0, "fixed": [], "unfixed": []}
    if not mc_version or loader not in ("fabric", "quilt"):
        return result
    runtime = mods._doctor_runtime_versions(mc_version, loader, version_id)
    entries = _scan(mc_version, loader, version_id)
    result["checked"] = len(entries)
    deadline = time.monotonic() + REPAIR_SECONDS
    tried, errors, network_down = set(), {}, False
    for _ in range(MAX_REPAIRS):
        missing = _missing(entries, runtime)
        pending = next((key for key in missing if key not in tried), None)
        if pending is None or not auto_fix:
            break
        tried.add(pending)
        owners = missing[pending]
        if status_cb:
            status_cb(f"Doctor: repairing {pending}")
        try:
            # Restore a compatible copy already on disk without a download.
            disabled = next((item for item, meta, provided in entries
                             if not item.get("enabled") and not item.get("protected")
                             and item["filename"].endswith(".jar.disabled")
                             and _usable(meta, provided, pending, owners, entries,
                                         runtime, mc_version, loader)), None)
            if disabled:
                path = os.path.join(mods.get_profile_dir(mc_version, loader, version_id),
                                    disabled["filename"])
                candidate = {"filename": disabled["filename"].removesuffix(".disabled")}
                _activate(path, candidate, pending, entries, mc_version, loader, version_id)
                fix = "re-enabled the compatible installed dependency"
            else:
                remaining = deadline - time.monotonic()
                if not check_online or network_down or remaining <= 0:
                    raise ValueError("Download unavailable; connect to the internet and retry Play")
                timeout = (min(3, remaining), min(10, remaining))
                # Fabric API submodules have no separate Modrinth project.
                project = "fabric-api" if pending == "fabric" or pending.startswith("fabric-") else pending
                predicates = None if project != pending else [pred for _, pred in owners]
                candidate = mods.get_mod_download(
                    project, mc_version=mc_version, loader=loader, timeout=timeout,
                    attempts=mods.LAUNCH_LOOKUP_ATTEMPTS, version_predicates=predicates)
                if not candidate:
                    raise ValueError("No compatible dependency download was found; check this instance's mods")
                with tempfile.TemporaryDirectory(prefix=".cubeon-dependency-",
                                                 dir=mods.get_profile_dir(mc_version, loader, version_id)) as stage:
                    path = _stage(candidate, stage, timeout, deadline)
                    meta, provided = mods._doctor_metadata(path, loader)
                    if not _usable(meta, provided, pending, owners, entries,
                                   runtime, mc_version, loader):
                        raise ValueError("The downloaded jar does not satisfy the installed mods' requirements")
                    _activate(path, candidate, project, entries, mc_version, loader, version_id)
                fix = "installed and verified the compatible dependency"
            entries = _scan(mc_version, loader, version_id)
            if pending in _missing(entries, runtime):
                raise ValueError("The dependency is still unsatisfied after repair")
            result["fixed"].append({"dependency": pending, "fix": fix})
        except Exception as error:
            errors[pending] = str(error)
            if isinstance(error, net.DownloadError) and not isinstance(error, net.HTTPStatusError):
                network_down = True
    providers = _providers(entries)
    for identity, owners in _missing(entries, runtime).items():
        for item, predicate in owners:
            name = item.get("display_name") or item["filename"]
            found = providers.get(identity)
            detail = f"{name} requires {identity} {predicate}"
            detail += f" (installed: {found})" if found is not None else " (missing)"
            result["unfixed"].append({"dependency": identity, "mod": name,
                                      "detail": detail, "error": errors.get(identity, "Retry Play to continue dependency repair")})
    return result
