"""Provider identities and the CurseForge adapter for the individual Mods catalogue.

Modrinth's established public functions remain in mods.py. Neither a provider
failure nor missing credentials is a successful empty compatibility lookup.
"""
import re
from itertools import zip_longest
from urllib.parse import urlsplit

from . import local_cache, net

SOURCES = ("modrinth", "curseforge")
LABELS = {"modrinth": "Modrinth", "curseforge": "CurseForge"}
LOADERS = {"forge": 1, "fabric": 4, "quilt": 5, "neoforge": 6}
CATEGORIES = {
    "performance": 6814, "optimization": 6814, "worldgen": 406,
    "technology": 412, "magic": 419, "adventure": 422, "decoration": 424,
    "utility": 5191, "storage": 420, "food": 436, "mobs": 411,
    "equipment": 434, "library": 421,
}
MAX_DEPENDENCIES = 100
MAX_FILE_PAGES = 20


class ExternalDownloadRequired(ValueError):
    def __init__(self, url):
        self.url = url
        super().__init__("This file must be downloaded on CurseForge. Use the official page, then Import from file.")


class ReleasePage(list):
    def __init__(self, values=(), *, next_offset=None):
        super().__init__(values)
        self.next_offset = next_offset


def source_of(item):
    source = item.get("source") or "modrinth"
    if source not in SOURCES:
        raise ValueError(f"Unknown mod source: {source}")
    return source


def identity(item, reference=None):
    ref = reference or item.get("project_id") or item.get("slug") or item.get("title") or ""
    return f"{source_of(item)}:{ref}"


def resolve_ref(ref, source="modrinth"):
    ref = str(ref or "")
    if ":" in ref and ref.split(":", 1)[0] in SOURCES:
        source, ref = ref.split(":", 1)
    if source not in SOURCES:
        raise ValueError(f"Unknown mod source: {source}")
    return source, ref


def interleave(mr_hits, cf_hits):
    result, seen = [], set()
    for pair in zip_longest(mr_hits, cf_hits):
        for hit in pair:
            if hit is not None and identity(hit) not in seen:
                seen.add(identity(hit))
                result.append(hit)
    return result


def reference(query):
    """Recognize provider project/version pages, never arbitrary download URLs."""
    try:
        parsed = urlsplit(query if "://" in query else "https://" + query)
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    parts = parsed.path.strip("/").split("/")
    host = parsed.netloc.lower().removeprefix("www.")
    if host == "modrinth.com" and len(parts) >= 2 and parts[0] in ("mod", "project"):
        source, project = "modrinth", parts[1]
        file_id = parts[3] if len(parts) >= 4 and parts[2] == "version" else None
    elif host == "curseforge.com" and len(parts) >= 3 and parts[:2] == ["minecraft", "mc-mods"]:
        source, project = "curseforge", parts[2]
        file_id = parts[4] if len(parts) >= 5 and parts[3] == "files" and parts[4].isdigit() else None
    else:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_-]+", project):
        return None
    if file_id and not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
        return None
    return {"source": source, "project": project, "file_id": file_id}


def cached(namespace, key, fetch, *, force=False, max_age=6 * 3600):
    if force:
        return local_cache.set(namespace, key, fetch())
    previous = local_cache.get_stale(namespace, key)
    negative = previous == [] or (isinstance(previous, dict) and previous.get("items") == [])
    return local_cache.cached_call(namespace, key, fetch, max_age=60 if negative else max_age,
                                   background_refresh=False, stale_ok=not negative)


def _request(path, params=None, *, timeout=(3, 10), cancel_event=None):
    # Share the existing credential precedence and HTTP implementation with packs.
    from .modpacks import _cf_request
    net.check_cancelled(cancel_event)
    response = _cf_request(path, params=params, timeout=timeout)
    net.check_cancelled(cancel_event)
    if not isinstance(response, dict) or "data" not in response:
        raise ValueError("CurseForge returned an invalid response. Retry the request.")
    return response


def _project(hit):
    if not isinstance(hit, dict) or not hit.get("id") or hit.get("classId", 6) != 6:
        raise ValueError("This CurseForge project is not a Minecraft mod.")
    authors = hit.get("authors") or []
    links = hit.get("links") or {}
    return dict(source="curseforge", project_id=str(hit["id"]), slug=hit.get("slug"),
                title=hit.get("name") or "Mod", description=hit.get("summary") or "",
                icon_url=(hit.get("logo") or {}).get("thumbnailUrl"),
                author=", ".join(a.get("name", "") for a in authors),
                downloads=hit.get("downloadCount") or 0,
                website_url=links.get("websiteUrl"), source_url=links.get("sourceUrl"),
                issues_url=links.get("issuesUrl"), wiki_url=links.get("wikiUrl"),
                categories=[c.get("name", "") for c in hit.get("categories") or []],
                gallery=[dict(url=s.get("url"), title=s.get("title") or "")
                         for s in hit.get("screenshots") or [] if s.get("url")],
                project_type="mod", allow_distribution=hit.get("allowModDistribution") is not False)


def search(query, mc_version=None, loader=None, categories=None, limit=24, offset=0, *, force=False):
    from .modpacks import curseforge_enabled
    if not curseforge_enabled():
        raise ValueError("CurseForge search is unavailable: no API key is configured.")
    params = dict(gameId=432, classId=6, searchFilter=query, sortField=1 if query else 2,
                  sortOrder="desc", index=offset, pageSize=min(limit, 50))
    if mc_version:
        params["gameVersion"] = mc_version
    if loader:
        params["modLoaderType"] = LOADERS[loader]
    if categories:
        import json
        params["categoryIds"] = json.dumps(sorted({CATEGORIES[c] for c in categories}))

    def fetch():
        data = _request("/mods/search", params)["data"]
        if not isinstance(data, list):
            raise ValueError("CurseForge returned an invalid search page.")
        return [dict(_project(h), search_query=query,
                     compatibility_target=[mc_version, loader] if mc_version and loader else None)
                for h in data]
    return cached("cf_mod_search", params, fetch, force=force)


def details(ref, *, force=False, description=True):
    def fetch():
        if str(ref).isdigit():
            data = _request(f"/mods/{ref}")["data"]
        else:
            matches = _request("/mods/search", dict(gameId=432, classId=6, slug=ref, pageSize=1))["data"]
            if not matches:
                raise ValueError("CurseForge mod not found.")
            data = matches[0]
        return _project(data)
    project = cached("cf_mod_details", str(ref), fetch, force=force)
    if not description:
        return project
    def body():
        return _request(f"/mods/{project['project_id']}/description")["data"]
    try:
        content = cached("cf_mod_body", project["project_id"], body, force=force)
    except Exception:
        content = project.get("description", "")
    return dict(project, body=content)


def _file(raw, project, mc_version, loader):
    if not isinstance(raw, dict) or str(raw.get("modId")) != project["project_id"]:
        raise ValueError("CurseForge returned a file belonging to another project.")
    tags = raw.get("gameVersions") or []
    compatible = (not mc_version or mc_version in tags) and (not loader or loader.lower() in [str(t).lower() for t in tags])
    url = raw.get("downloadUrl") if project["allow_distribution"] and raw.get("isAvailable", True) else None
    from .modpacks import _host_allowed
    if url and not _host_allowed(url):
        raise ValueError("CurseForge returned an untrusted download URL.")
    return dict(source="curseforge", project_id=project["project_id"], slug=project.get("slug"),
                id=str(raw["id"]), file_id=str(raw["id"]), name=raw.get("displayName") or "",
                version_number=raw.get("displayName") or "", filename=raw.get("fileName"), url=url,
                website_url=f"{project.get('website_url') or 'https://www.curseforge.com/minecraft/mc-mods/' + str(project.get('slug'))}/files/{raw['id']}",
                game_versions=[t for t in tags if str(t)[:1].isdigit()],
                loaders=[t.lower() for t in tags if str(t).lower() in LOADERS],
                compatible=compatible, version_type={1: "release", 2: "beta", 3: "alpha"}.get(raw.get("releaseType"), "release"),
                date_published=raw.get("fileDate") or "", downloads=raw.get("downloadCount") or 0,
                size_kb=round((raw.get("fileLength") or 0) / 1024, 1),
                dependencies=raw.get("dependencies") or [],
                hashes={"sha1": h["value"] for h in raw.get("hashes") or [] if h.get("algo") == 1},
                icon_url=project.get("icon_url"))


def versions(ref, mc_version=None, loader=None, *, offset=0, limit=50, file_id=None,
             force=False, timeout=(3, 10), cancel_event=None, allow_network=True):
    key = dict(project=str(ref), mc=mc_version, loader=loader, offset=offset, limit=limit, file=file_id)
    def fetch():
        project = details(ref, force=force, description=False)
        params = dict(index=offset, pageSize=min(limit, 50))
        if mc_version:
            params["gameVersion"] = mc_version
        if loader:
            params["modLoaderType"] = LOADERS[loader]
        path = f"/mods/{project['project_id']}/files"
        payload = _request(f"{path}/{file_id}" if file_id else path,
                           None if file_id else params, timeout=timeout, cancel_event=cancel_event)
        data = [payload["data"]] if file_id else payload["data"]
        if not isinstance(data, list):
            raise ValueError("CurseForge returned an invalid release page.")
        items = [_file(v, project, mc_version, loader) for v in data]
        items.sort(key=lambda v: (v["date_published"], int(v["id"])), reverse=True)
        count = (payload.get("pagination") or {}).get("totalCount")
        more = not file_id and (offset + len(data) < count if isinstance(count, int) else len(data) == min(limit, 50))
        return dict(items=items, next_offset=offset + len(data) if more and data else None)
    net.check_cancelled(cancel_event)
    payload = (cached("cf_mod_versions", key, fetch, force=force) if allow_network
               else local_cache.get_stale("cf_mod_versions", key)) or dict(items=[])
    net.check_cancelled(cancel_event)
    return ReleasePage(payload["items"], next_offset=payload.get("next_offset"))


def download(ref, mc_version=None, loader=None, *, file_id=None, force=False,
             timeout=(3, 10), cancel_event=None, version_predicates=None, **_):
    offset = 0
    restricted = None
    for _page in range(MAX_FILE_PAGES):
        releases = versions(ref, mc_version, loader, file_id=file_id, offset=offset,
                            force=force, timeout=timeout, cancel_event=cancel_event)
        for release in releases:
            if not release["compatible"] or not str(release.get("filename") or "").lower().endswith(".jar"):
                continue
            if not release["url"]:
                restricted = release["website_url"]
                continue
            # CF displayName is not a semantic mod version. The resolver checks
            # actual JAR predicates after staging; don't compare names to ranges.
            return release
        if releases.next_offset is None:
            if restricted:
                raise ExternalDownloadRequired(restricted)
            return None
        offset = releases.next_offset
    raise ValueError("Too many CurseForge release pages. Open the official project page to choose a file.")


def required_dependencies(root, mc_version, loader, *, cancel_event=None):
    """Resolve every required edge before publishing the root JAR."""
    resolved = {root["project_id"]: root}
    queue = list(root.get("dependencies") or [])
    while queue:
        net.check_cancelled(cancel_event)
        dep = queue.pop(0)
        if dep.get("relationType") != 3:
            continue
        project = str(dep.get("modId") or "")
        if not project.isdigit():
            raise ValueError("Invalid required CurseForge dependency.")
        if project in resolved:
            continue
        if len(resolved) >= MAX_DEPENDENCIES:
            raise ValueError("Too many required mod dependencies.")
        candidate = download(project, mc_version, loader, cancel_event=cancel_event)
        if not candidate:
            raise ValueError(f"Required CurseForge dependency {project} has no matching build.")
        resolved[project] = candidate
        queue.extend(candidate["dependencies"])
    return [v for k, v in resolved.items() if k != root["project_id"]]


def install(ref, filename, mc_version, loader, *, file_id=None, version_id=None,
            progress_cb=None, status_cb=None, cancel_event=None):
    from . import mods, global_mod_cache
    import os
    mods.require_mod_loader(mc_version, loader, "install a mod")
    root = download(ref, mc_version, loader, file_id=file_id, cancel_event=cancel_event)
    if not root or root["filename"] != filename:
        raise ValueError("The selected CurseForge file no longer matches this instance. Refresh its releases.")
    if status_cb:
        status_cb("Checking dependencies...")
    dependencies = required_dependencies(root, mc_version, loader, cancel_event=cancel_event)
    directory = mods.resolve_profile_dir(mc_version, loader, version_id)
    existing = mods.list_mods(mc_version, loader, version_id)
    pending, skipped = [root], 0
    for dep in dependencies:
        if any(item.get("enabled") and dep.get("hashes") and global_mod_cache._matches_hashes(
                os.path.join(directory, item["filename"]), dep["hashes"]) for item in existing):
            skipped += 1
        else:
            pending.append(dep)
    installed, failed = [], []
    total = len(pending)
    for index, release in enumerate(pending):
        net.check_cancelled(cancel_event)
        if status_cb:
            status_cb(f"Downloading {release['filename']}")
        def progress(done, size):
            net.check_cancelled(cancel_event)
            if progress_cb:
                progress_cb(index + min(1, done / size) if size else index, total)
        try:
            mods.download_mod(release["url"], release["filename"], progress_cb=progress,
                              mc_version=mc_version, loader=loader, version_id=version_id,
                              slug=release.get("slug"), project_id=release["project_id"],
                              hashes=release["hashes"], source="curseforge", file_id=release["id"],
                              icon_url=release.get("icon_url"), cancel_event=cancel_event)
            installed.append(release["filename"])
            if progress_cb:
                progress_cb(index + 1, total)
        except net.DownloadCancelled:
            raise
        except Exception as error:
            if index == 0:
                raise
            failed.append(f"{release['filename']}: {error}")
    net.check_cancelled(cancel_event)
    from .mod_dependencies import run_dependency_doctor
    report = run_dependency_doctor(mc_version, loader, version_id=version_id,
                                   status_cb=status_cb, auto_fix=False, check_online=False)
    failed.extend(item["detail"] for item in report["unfixed"])
    return dict(installed=installed, skipped=skipped, failed=failed, compatibility=report)
