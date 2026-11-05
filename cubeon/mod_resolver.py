"""Bounded, non-interactive resolution of an installed mod dependency graph.

Search uses actual staged JAR descriptors, including nested modules. A solution
retains every enabled mod identity and is published as one reversible swap.
"""
from dataclasses import dataclass
from functools import cmp_to_key
import json
import os
import tempfile
import time
import zipfile

from . import mods, net

MAX_STATES = 96
MAX_CANDIDATES = 8


@dataclass
class Choice:
    item: dict
    meta: dict
    provided: dict
    path: str
    candidate: dict | None = None
    project: str | None = None

    @property
    def key(self):
        return str(self.meta.get("id") or "@" + self.item["filename"]).lower()


def _providers(selected, runtime):
    providers = dict(runtime)
    owners = {}
    for key, choice in selected.items():
        for identity, version in choice.provided.items():
            if identity in mods.DOCTOR_RUNTIME_IDS:
                continue
            if providers.get(identity) is None or mods._cmp_versions(version, providers[identity]) > 0:
                providers[identity] = version
                owners[identity] = key
    return providers, owners


def _descriptors(choice, providers):
    descriptors = choice.meta.get("_descriptors") or [choice.meta]
    for descriptor in descriptors:
        if descriptor.get("environment") == "server":
            continue
        identity = str(descriptor.get("id") or "").lower()
        # Fabric selects the highest bundled provider; a superseded nested
        # module's constraints do not belong to the active graph.
        if identity != choice.key and providers.get(identity) is not None \
                and mods._cmp_versions(providers[identity], descriptor.get("version") or "") > 0:
            continue
        yield descriptor


def issues(selected, runtime, mc_version, loader):
    providers, owners = _providers(selected, runtime)
    problems = []
    for key, choice in selected.items():
        name = choice.meta.get("name") or choice.item.get("display_name") or choice.item["filename"]
        reason = mods._doctor_local_incompatibility(choice.meta, mc_version, loader)
        if reason:
            problems.append(dict(kind="incompatible", owner=key, dependency=key, mod=name, detail=f"{name}: {reason}"))
        if not choice.meta:
            try:
                with zipfile.ZipFile(choice.path) as archive:
                    malformed = any(path in archive.namelist() for path in (
                        "fabric.mod.json", "quilt.mod.json", "META-INF/mods.toml", "META-INF/neoforge.mods.toml"))
            except (OSError, zipfile.BadZipFile):
                malformed = True
            if malformed:
                problems.append(dict(kind="unreadable", owner=key, dependency=key, mod=name,
                                     detail=f"{name}: the mod descriptor or JAR is unreadable"))
        for descriptor in _descriptors(choice, providers):
            for identity, predicate in (descriptor.get("depends") or {}).items():
                identity = str(identity).lower()
                actual = providers.get(identity)
                if identity in runtime and actual is None:
                    continue  # Runtime is installed but its version is unknown.
                if actual is None or not mods.version_satisfies(actual, predicate):
                    # The root's Minecraft requirement was already described above.
                    if reason and str(descriptor.get("id") or "").lower() == key and identity == "minecraft":
                        continue
                    installed = f"installed: {actual}" if actual is not None else "missing"
                    problems.append(dict(kind="required", owner=key, dependency=identity, mod=name,
                                         predicate=predicate, detail=f"{name} requires {identity} {predicate} ({installed})"))
            for identity, predicate in (descriptor.get("breaks") or {}).items():
                identity = str(identity).lower()
                actual = providers.get(identity)
                if actual is not None and mods.version_satisfies(actual, predicate):
                    problems.append(dict(kind="conflict", owner=key, dependency=identity, mod=name,
                                         predicate=predicate, detail=f"{name} {descriptor.get('version') or ''} conflicts with {identity} {actual} ({predicate})"))
    return problems


class Resolver:
    def __init__(self, entries, runtime, mc_version, loader, version_id,
                 deadline, max_repairs, check_online, stage_download, scan, status_cb,
                 *, snapshot=None):
        self.mc, self.loader, self.version_id = mc_version, loader, version_id
        self.runtime, self.deadline, self.max_repairs = runtime, deadline, max_repairs
        self.online, self.stage_download, self.scan, self.status = check_online, stage_download, scan, status_cb
        self.directory = mods.get_profile_dir(mc_version, loader, version_id)
        self.snapshot = snapshot if snapshot is not None else mods._doctor_profile_snapshot(self.directory)
        self.originals = [Choice(item, meta or {}, provided,
                                 os.path.join(self.directory, item["filename"]))
                          for item, meta, provided in entries]
        self.groups = {}
        for choice in self.originals:
            self.groups.setdefault(choice.key, []).append(choice)
        self.initial = {}
        for key, group in self.groups.items():
            enabled = [choice for choice in group if choice.item.get("enabled")]
            if enabled:
                enabled.sort(key=cmp_to_key(lambda a, b: mods._cmp_versions(
                    b.meta.get("version") or "", a.meta.get("version") or "")))
                enabled.sort(key=lambda c: (not c.item.get("protected"),
                                           bool(mods._doctor_local_incompatibility(c.meta, self.mc, self.loader))))
                self.initial[key] = enabled[0]
        self.visited, self.downloads, self.queries = set(), {}, {}
        self.errors, self.network_down, self.transfers = {}, False, 0
        self.stage = None

    def _state_key(self, selected):
        return tuple((key, json.dumps(choice.meta, sort_keys=True, default=str),
                      tuple(sorted(choice.provided.items()))) for key, choice in sorted(selected.items()))

    def _timeout(self):
        remaining = self.deadline - time.monotonic()
        if not self.online or self.network_down or remaining <= 0:
            raise ValueError("Download unavailable; connect to the internet and retry Play")
        return min(3, remaining), min(10, remaining)

    def _network(self, cache_key, function):
        if cache_key not in self.queries:
            try:
                self.queries[cache_key] = function(self._timeout())
            except Exception as error:
                if isinstance(error, net.DownloadError) and not isinstance(error, net.HTTPStatusError):
                    self.network_down = True
                self.queries[cache_key] = []
                raise
        return self.queries[cache_key]

    def _project(self, key):
        for choice in self.groups.get(key, []):
            reference = mods._mod_ref(choice.item)
            if reference:
                return reference
        if key == "fabric" or key.startswith("fabric-"):
            return "fabric-api"
        return {"cloth_config": "cloth-config", "architectury": "architectury-api"}.get(key, key)

    def _stage_choice(self, candidate, key, project):
        if not isinstance(candidate, dict) or not candidate.get("url") or not candidate.get("filename"):
            return None
        token = candidate["url"]
        if token not in self.downloads:
            if self.transfers >= self.max_repairs:
                raise ValueError("Automatic repair download limit reached; retry Play")
            self.transfers += 1
            folder = tempfile.mkdtemp(prefix="candidate-", dir=self.stage)
            candidate = dict(candidate, filename=mods._safe_download_filename(candidate["filename"]))
            try:
                path = self.stage_download(candidate, folder, self._timeout(), self.deadline)
                metadata, provided = mods._doctor_metadata(path, self.loader)
                if not metadata or mods._doctor_local_incompatibility(metadata, self.mc, self.loader):
                    raise ValueError("The downloaded JAR is not compatible with this Minecraft version and loader")
                self.downloads[token] = Choice(dict(filename=candidate["filename"], enabled=True),
                                               metadata, provided, path, candidate, project)
            except Exception as error:
                if isinstance(error, net.DownloadError) and not isinstance(error, net.HTTPStatusError):
                    self.network_down = True
                self.downloads[token] = None
                raise
        choice = self.downloads[token]
        if choice is None:
            return None
        if self.groups.get(key):
            # An existing root (including an umbrella of nested modules) must
            # keep its identity; a similarly named project is insufficient.
            return choice if choice.key == key else None
        return choice if key in choice.provided else None

    def _choices(self, key, selected, problem):
        current = selected.get(key)
        if any(c.item.get("protected") and c.item.get("enabled") for c in self.groups.get(key, [])):
            return
        local = list(self.groups.get(key, []))
        if key not in self.groups:
            local.extend(choice for choice in self.originals if not choice.item.get("enabled") and key in choice.provided)
        for choice in local:
            if choice is not current and not choice.item.get("protected") and choice.meta \
                    and not mods._doctor_local_incompatibility(choice.meta, self.mc, self.loader):
                yield choice
        project = self._project(key)
        if key.startswith("@") or key in mods.DOCTOR_RUNTIME_IDS:
            return
        predicates = None
        if project == key and problem["kind"] == "required" and key == problem["dependency"]:
            providers, _ = _providers(selected, self.runtime)
            predicates = [predicate for choice in selected.values() for desc in _descriptors(choice, providers)
                          for identity, predicate in (desc.get("depends") or {}).items() if identity.lower() == key]
        query = ("latest", project, json.dumps(predicates, sort_keys=True))
        latest = self._network(query, lambda timeout: mods.get_mod_download(
            project, mc_version=self.mc, loader=self.loader, timeout=timeout,
            attempts=mods.LAUNCH_LOOKUP_ATTEMPTS, version_predicates=predicates))
        if latest:
            try:
                choice = self._stage_choice(latest, key, project)
                if choice:
                    yield choice
            except Exception as error:
                self.errors[key] = str(error)
        releases = self._network(("versions", project), lambda timeout: mods.get_mod_versions(
            project, mc_version=self.mc, loader=self.loader, timeout=timeout,
            attempts=mods.LAUNCH_LOOKUP_ATTEMPTS))
        releases = [v for v in releases or [] if v.get("compatible") and v.get("url")
                    and str(v.get("filename") or "").lower().endswith(".jar")]
        releases.sort(key=lambda v: (v.get("version_type") == "release", v.get("date_published") or ""), reverse=True)
        for release in releases[:MAX_CANDIDATES]:
            try:
                choice = self._stage_choice(release, key, project)
                if choice:
                    yield choice
            except Exception as error:
                self.errors[key] = str(error)
                if self.network_down:
                    return

    def _search(self, selected, depth=0):
        signature = self._state_key(selected)
        if signature in self.visited or len(self.visited) >= MAX_STATES or depth > self.max_repairs:
            return None
        self.visited.add(signature)
        problems = issues(selected, self.runtime, self.mc, self.loader)
        if not problems:
            return selected
        if depth and time.monotonic() >= self.deadline:
            return None
        problem = problems[0]
        _, providers = _providers(selected, self.runtime)
        dependency = problem["dependency"]
        keys = [providers.get(dependency, dependency), problem["owner"]]
        # If several owners demand incompatible versions, their own compatible
        # releases can change those constraints as part of the same solution.
        if problem["kind"] == "required":
            for owner, choice in selected.items():
                if any(dependency in (desc.get("depends") or {}) for desc in _descriptors(choice, {})):
                    keys.append(owner)
        for key in dict.fromkeys(keys):
            try:
                for choice in self._choices(key, selected, problem):
                    proposed = dict(selected)
                    if key in proposed:
                        proposed.pop(key)
                    proposed[choice.key] = choice
                    solution = self._search(proposed, depth + 1)
                    if solution is not None:
                        return solution
            except Exception as error:
                self.errors[dependency] = str(error)
                self.errors[key] = str(error)
        return None

    def _publish(self, solution):
        if mods._doctor_profile_snapshot(self.directory) != self.snapshot:
            raise ValueError("Mods changed during the automatic check; retry Play")
        removed = [choice for choice in self.originals if choice.item.get("enabled")
                   and solution.get(choice.key) is not choice]
        if any(choice.item.get("protected") for choice in removed):
            raise ValueError("A protected mod cannot be replaced automatically")
        changed = [choice for choice in solution.values() if not choice.item.get("enabled")
                   or choice not in self.originals]
        destinations = [os.path.join(self.directory, c.item["filename"].removesuffix(".disabled")) for c in changed]
        if len(set(destinations)) != len(destinations):
            raise ValueError("Two replacement mods use the same filename")
        affected = {choice.path for choice in removed}
        for destination in destinations:
            if os.path.lexists(destination) and destination not in affected:
                raise ValueError("A replacement filename is already used by an unrelated mod")
        moved, placed, sidecars = [], [], {}
        try:
            for choice in removed:
                backup = choice.path + ".disabled"
                suffix = 1
                while os.path.lexists(backup):
                    backup = choice.path + f".cubeon-previous-{suffix}"
                    suffix += 1
                os.replace(choice.path, backup)
                moved.append((choice.path, backup))
            for choice, destination in zip(changed, destinations):
                os.replace(choice.path, destination)
                placed.append((choice.path, destination))
                sidecar = destination + mods.MOD_META_SUFFIX
                try:
                    with open(sidecar, "rb") as source:
                        sidecars[sidecar] = source.read()
                except FileNotFoundError:
                    sidecars[sidecar] = None
                if choice.candidate:
                    from .global_mod_cache import _matches_hashes
                    if not _matches_hashes(destination, choice.candidate.get("hashes") or {}):
                        raise ValueError("The staged mod changed after download verification")
                    mods._write_meta(self.directory, os.path.basename(destination), choice.project,
                                     project_id=choice.candidate.get("project_id") or choice.project,
                                     url=choice.candidate.get("url"))
            published_snapshot = mods._doctor_profile_snapshot(self.directory)
            actual = {}
            for item, meta, provided in self.scan(self.mc, self.loader, self.version_id):
                if not item.get("enabled"):
                    continue
                choice = Choice(item, meta or {}, provided,
                                os.path.join(self.directory, item["filename"]))
                if choice.key in actual:
                    raise ValueError("Duplicate mods appeared during the automatic repair; retry Play")
                actual[choice.key] = choice
            if mods._doctor_profile_snapshot(self.directory) != published_snapshot:
                raise ValueError("Mods changed during the final automatic check; retry Play")
            if self._state_key(actual) != self._state_key(solution) \
                    or issues(actual, self.runtime, self.mc, self.loader):
                raise ValueError("The installed mod set did not pass the final compatibility check")
        except BaseException:
            for sidecar, previous in sidecars.items():
                if previous is None:
                    if os.path.exists(sidecar):
                        os.remove(sidecar)
                else:
                    with open(sidecar, "wb") as target:
                        target.write(previous)
            for source, destination in reversed(placed):
                os.replace(destination, source)
            for source, backup in reversed(moved):
                os.replace(backup, source)
            raise
        keys = dict.fromkeys([c.key for c in changed] + [c.key for c in removed])
        return [dict(dependency=key, fix="installed and verified the compatible dependency"
                     if solution[key].candidate else "re-enabled the compatible installed dependency"
                     if not solution[key].item.get("enabled") else "kept the compatible build and backed up duplicate copies")
                for key in keys]

    def run(self, auto_fix):
        if mods._doctor_profile_snapshot(self.directory) != self.snapshot:
            return dict(checked=len(self.originals), fixed=[], unfixed=[dict(
                dependency="profile", mod="Mod profile", kind="profile-changed",
                detail="Mods changed during the automatic check", error="Retry Play")])
        problems = issues(self.initial, self.runtime, self.mc, self.loader)
        duplicates = any(sum(bool(c.item.get("enabled")) for c in group) > 1 for group in self.groups.values())
        result = dict(checked=len(self.originals), fixed=[], unfixed=[])
        if not problems and not duplicates:
            return result
        if auto_fix:
            if self.status:
                self.status("Doctor: checking mod version conflicts")
            with tempfile.TemporaryDirectory(prefix=".cubeon-dependency-", dir=self.directory) as stage:
                self.stage = stage
                solution = self._search(self.initial)
                if solution is not None:
                    try:
                        result["fixed"] = self._publish(solution)
                        return result
                    except Exception as error:
                        self.errors["publish"] = str(error)
        for problem in problems:
            result["unfixed"].append(dict(dependency=problem["dependency"], mod=problem["mod"],
                                           kind=problem["kind"], detail=problem["detail"],
                                           error=self.errors.get("publish") or self.errors.get(problem["dependency"])
                                           or "No compatible mod set was found within the automatic repair limit; check these mods or retry Play"))
        if duplicates and not result["unfixed"]:
            result["unfixed"].append(dict(dependency="duplicates", mod="Duplicate mods",
                                           detail="Multiple enabled JARs provide the same mod",
                                           error=self.errors.get("publish") or "Retry Play to keep one compatible build"))
        return result
