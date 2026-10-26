"""Vanilla cannot install mods/shaders; resource packs remain supported."""
import inspect
import json
import os
import sys
import tempfile
import zipfile
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

import flet as ft
from cubeon import content, mods
from cubeon.mod_loaders import MOD_CAPABLE_LOADERS
from cubeon.theme import THEME, section_label
import _fuzz_common
from app_driver import DriverPage
from ui.mods_tab import build_mods_tab

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'}   {label}")


def rejects(handler):
    try:
        handler()
    except ValueError as error:
        return "Vanilla" in str(error)
    return False


with tempfile.TemporaryDirectory() as directory:
    jar_path = os.path.join(directory, "test.jar")
    with open(jar_path, "wb") as output:
        output.write(b"jar")
    check("local mod installs reject vanilla", rejects(lambda: mods.install_local_mod(jar_path, "1.21.1", "vanilla")))
    with patch.object(mods.net, "download_to") as download:
        check("remote mod installs reject vanilla before downloading", rejects(lambda: mods.download_mod("https://invalid/test.jar", "test.jar", mc_version="1.21.1", loader="vanilla")))
        check("dependency installs reject vanilla before resolving a project", rejects(lambda: mods.install_mod_with_dependencies("https://invalid/test.jar", "test.jar", "1.21.1", "vanilla")))
        check("rejected mod installs never start a download", download.call_count == 0)
    shader_path = os.path.join(directory, "test.zip")
    with zipfile.ZipFile(shader_path, "w") as archive:
        archive.writestr("shaders/test.fsh", "void main() {}")
    with patch.object(content, "_store_entry") as store, patch.object(content.net, "download_to") as download:
        check("local shader installs reject vanilla before storing bytes", rejects(lambda: content.install_local_content("shader", shader_path, "1.21.1", loader="vanilla")))
        check("remote shaders reject vanilla before network I/O", rejects(lambda: content.download_content("shader", "https://invalid/test.zip", "test.zip", mc_version="1.21.1", loader="vanilla")))
        check("rejected shaders touch neither the store nor network", store.call_count == 0 and download.call_count == 0)
    resource_path = os.path.join(directory, "resources.zip")
    with zipfile.ZipFile(resource_path, "w") as archive:
        archive.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 34, "description": "Test"}}))
        archive.writestr("assets/minecraft/test.txt", "test")
    installed = content.install_local_content("resourcepack", resource_path, "1.21.1", loader="vanilla")
    check("a real texture pack still installs into vanilla", os.path.isfile(os.path.join(content.resolve_content_profile_dir("resourcepack", "1.21.1", "vanilla"), installed)))

for loader in MOD_CAPABLE_LOADERS:
    mods.require_mod_loader("1.21.1", loader, "install a mod")
    content._require_install_target("shader", "1.21.1", loader)
check("all four supported mod loaders remain valid, not only Fabric", set(MOD_CAPABLE_LOADERS) == {"fabric", "quilt", "forge", "neoforge"})

_fuzz_common.install_safe_stubs()
page = DriverPage()
state = {"selected_mc_version": "1.21.1", "mod_loader": "vanilla"}
root, refresh, _recommend, _browse = build_mods_tab(page, {}, state, ft.Dropdown(value="1.21.1"), section_label=section_label, **THEME)
refresh()
closure = inspect.getclosurevars(refresh).nonlocals
install_button = closure["local_install_btn"]
check("the vanilla Mods install button is disabled", install_button.disabled)
choose_type = inspect.getclosurevars(closure["_can_install"]).nonlocals["_ct"]
active_content = inspect.getclosurevars(choose_type).nonlocals["active_content"]
active_content["type"] = "shader"
refresh()
check("the vanilla Shader install button is disabled", install_button.disabled)
active_content["type"] = "resourcepack"
refresh()
check("the vanilla Resource Pack install button stays enabled", not install_button.disabled)
active_content["type"] = "mod"
state["mod_loader"] = "fabric"
refresh()
check("choosing Fabric re-enables installing mods", not install_button.disabled)

# 2026-10-25 report: "why can I install mods/shaders on plain vanilla". The
# switcher can read Fabric because another instance on the same MC version has
# it, or because Play is armed to install it - that must NOT make a plain
# vanilla folder accept content. The selected INSTANCE has to prove its loader.
state["installed"] = {"1.21.1"}
state["installed_meta"] = {"1.21.1": {"id": "1.21.1"}}
state["mod_loader"] = "fabric"
refresh()
check("a plain vanilla instance stays blocked even when the switcher says Fabric",
      install_button.disabled)
active_content["type"] = "shader"
refresh()
check("...and so do shaders", install_button.disabled)
active_content["type"] = "resourcepack"
refresh()
check("...while texture packs still work in vanilla", not install_button.disabled)
active_content["type"] = "mod"
state["pending_loader_install"] = {"version_id": "1.21.1", "loader": "fabric"}
refresh()
check("arming a Fabric install for the instance re-enables mods",
      not install_button.disabled)
state["pending_loader_install"] = None

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
