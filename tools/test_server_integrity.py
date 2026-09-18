import io
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import minekube as M, net, server as S

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def refused(label, action):
    try:
        action()
    except (RuntimeError, OSError, M.MinekubeError):
        check(label, True)
    else:
        check(label, False)


def jar(entries, size):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
        archive.writestr("payload.bin", b"a" * size)
    return stream.getvalue()


paper = jar({"META-INF/MANIFEST.MF": "Main-Class: io.papermc.paperclip.Main\n",
             "io/papermc/paperclip/Main.class": b"class"}, S.MIN_SERVER_BYTES)
connect = jar({"plugin.yml": "name: connect\nmain: example.Connect\n",
               "example/Connect.class": b"class"}, M.MIN_PLUGIN_BYTES)

with tempfile.TemporaryDirectory(prefix="cubeon-server-integrity-") as scratch:
    root = Path(scratch)
    source = root / "paper.jar"
    source.write_bytes(paper)
    plugin_source = root / "connect.jar"
    plugin_source.write_bytes(connect)
    servers = root / "servers"
    with patch.object(S, "SERVERS_DIR", str(servers)), \
            patch("cubeon.paths.ensure_disk_space"), \
            patch.object(S, "find_local_paper_jar", return_value=None):
        version = "1.21.11"
        S.install_server(version, local_jar_path=str(source))
        final = Path(S._typed_jar_path(version, S.SERVER_TYPE_PAPER))
        check("Paper install publishes a complete archive", final.read_bytes() == paper)
        check("Paper install is detected", S.is_server_installed(version))
        check("Paper install leaves no staging files", not list(final.parent.glob(".server-*")))
        with patch.object(S, "_server_jar_valid", return_value=True) as valid:
            check("installed types include each validated type",
                  S.get_installed_server_types(version) == list(S.SERVER_TYPES))
            check("every server type passes archive validation",
                  [call.args[0] for call in valid.call_args_list] ==
                  [S._typed_jar_path(version, t) for t in S.SERVER_TYPES])

        S.save_server_properties(version, {"motd": "keep my world"})
        S.set_eula_accepted(version, True)
        state = {name: (final.parent / name).read_bytes()
                 for name in ("server.properties", "eula.txt", "server_type.txt")}
        source.write_bytes(paper[:-30])
        refused("truncated Paper update is refused",
                lambda: S.install_server(version, local_jar_path=str(source)))
        check("failed Paper update preserves prior installation", final.read_bytes() == paper)
        check("failed Paper update preserves settings and consent",
              all((final.parent / name).read_bytes() == data for name, data in state.items()))
        check("failed Paper update cleans staging", not list(final.parent.glob(".server-*")))
        for label, data in (("truncated", paper[:-30]), ("too small", b"PK")):
            final.write_bytes(data)
            check(f"{label} Paper is not installed", not S.is_server_installed(version))
            check(f"{label} Paper excluded from installed types", not S.get_installed_server_types(version))
        final.write_bytes(paper)
        source.write_bytes(jar({"unrelated.txt": "not a server"}, S.MIN_SERVER_BYTES))
        refused("ordinary zip cannot replace Paper",
                lambda: S.install_server(version, local_jar_path=str(source)))
        corrupt = paper.replace(b"a" * 20, b"b" + b"a" * 19, 1)
        source.write_bytes(corrupt)
        refused("Paper CRC failure is refused",
                lambda: S.install_server(version, local_jar_path=str(source)))

        downloads = []

        def download(dest, url, **kwargs):
            downloads.append(dest)
            Path(dest).write_bytes(paper)
            callback = kwargs.get("progress_cb")
            if callback is not None:
                callback(len(paper), len(paper))
            return len(paper)

        with patch.object(S, "_get_paper_download_url", return_value=("https://example.invalid/paper", "1")), \
                patch.object(S.requests, "head", return_value=SimpleNamespace(headers={"content-length": str(len(paper))})), \
                patch.object(net, "download_to", side_effect=download):
            S.install_server(version)
            check("known-length download works with progress_cb=None", final.read_bytes() == paper)
            progress = []
            S.install_server(version, progress_cb=progress.append)
            check("provided progress callback receives bytes", progress == [len(paper)])
            check("Paper attempts use unique staging paths", len(set(downloads)) == 2)

        targets = []
        exits = []

        class Process:
            def __init__(self):
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self):
                return self.returncode

        old, replacement = Process(), Process()
        with patch.object(S, "world_lock_holder", return_value=None), \
                patch.object(S, "find_java_for_version", return_value="java"), \
                patch.object(S, "java_major_version", return_value=25), \
                patch.object(S, "high_ping_optimization_enabled", return_value=False), \
                patch.object(S.subprocess, "Popen", side_effect=[old, replacement]), \
                patch.object(S.threading, "Thread", side_effect=lambda target, **kw: SimpleNamespace(start=lambda: targets.append(target))):
            S.start_server(version, 1024, on_exit=exits.append)
            old.returncode = 0
            S.start_server(version, 1024, on_exit=exits.append)
            targets[0]()
            check("stale exit watcher keeps replacement", S._server_processes.get(version) is replacement)
            check("stale exit callback still reports exit", exits == [0])
            replacement.returncode = 0
            targets[1]()
            check("matching exit watcher removes its process", version not in S._server_processes)

        dest = Path(M.plugin_jar_path(version))
        with patch.object(M, "find_local_plugin", return_value=str(plugin_source)):
            M.install_plugin(version)
            check("local Connect install publishes valid archive", dest.read_bytes() == connect and M.is_plugin_installed(version))
            check("Connect success cleans staging", not list(dest.parent.glob(".connect-*")))
            dest.write_bytes(connect[:-30])
            check("partial Connect above size floor is not installed", not M.is_plugin_installed(version))
            dest.write_bytes(connect)
            stages = []

            def partial_copy(src, target):
                stages.append(target)
                Path(target).write_bytes(connect[:-30])
                raise OSError("interrupted copy")

            with patch.object(M.shutil, "copyfile", side_effect=partial_copy):
                refused("partial local Connect copy fails", lambda: M.install_plugin(version, force=True))
                check("partial copy preserves prior Connect", dest.read_bytes() == connect)
                dest.unlink()
                refused("partial first Connect copy fails", lambda: M.install_plugin(version))
                check("partial first copy is not installed", not M.is_plugin_installed(version))
            check("Connect stages uniquely inside plugins directory",
                  len(set(stages)) == 2 and all(Path(p).parent == dest.parent and Path(p) != dest for p in stages))
            check("Connect failure cleans staging", not list(dest.parent.glob(".connect-*")))
            plugin_source.write_bytes(jar({"plugin.yml": "name: unrelated\n"}, M.MIN_PLUGIN_BYTES))
            refused("wrong plugin marker is refused", lambda: M.install_plugin(version))
            plugin_source.write_bytes(connect.replace(b"a" * 20, b"b" + b"a" * 19, 1))
            refused("Connect CRC failure is refused", lambda: M.install_plugin(version))
            check("invalid Connect never reaches final path", not dest.exists())

        with patch.object(M, "find_local_plugin", return_value=None):
            def connect_download(target, url, **kwargs):
                Path(target).write_bytes(connect)
                return len(connect)

            with patch.object(net, "download_to", side_effect=connect_download):
                M.install_plugin(version)
                check("downloaded Connect passes complete validation", M.is_plugin_installed(version))

            def interrupted_download(target, url, **kwargs):
                Path(target + ".part").write_bytes(b"partial")
                raise net.DownloadError("interrupted")

            with patch.object(net, "download_to", side_effect=interrupted_download):
                refused("interrupted Connect download is refused", lambda: M.install_plugin(version, force=True))
                check("interrupted Connect download preserves installed bytes", dest.read_bytes() == connect)
                check("interrupted Connect download cleans nested partial", not list(dest.parent.glob(".connect-*")))
            with patch.object(S, "_get_paper_download_url", return_value=("https://example.invalid/paper", "1")), \
                    patch.object(S.requests, "head", return_value=SimpleNamespace(headers={})), \
                    patch.object(net, "download_to", side_effect=interrupted_download):
                refused("interrupted Paper download is refused", lambda: S.install_server(version))
                check("interrupted Paper download preserves installed bytes", final.read_bytes() == paper)
                check("interrupted Paper download cleans nested partial", not list(final.parent.glob(".server-*")))

host = "live-beru.play.minekube.net"
for address in (host, host + ":1", host + ":25565", host + ":65535"):
    check(f"public address preserves {address}",
          M.read_public_address("unused", log_lines=f"[Connect] Your public address: {address}") == address)
check("public address normalizes host case without dropping port",
      M.read_public_address("unused", log_lines=host.upper() + ":25566") == host + ":25566")
for port in ("0", "65536", "999999", "", "-1", "abc", "25565extra"):
    check(f"invalid public port {port!r} is rejected",
          M.read_public_address("unused", log_lines=host + ":" + port) is None)
for invalid in ("bad-.play.minekube.net", "-bad.play.minekube.net", "a" * 64 + ".play.minekube.net",
                host + ".invalid", "connect.minekube.com:25565"):
    check(f"invalid or excluded host {invalid!r} is rejected",
          M.read_public_address("unused", log_lines=invalid) is None)
check("latest announced address keeps its explicit port",
      M.read_public_address("unused", log_lines=host + ":25565\n" + host + ":25566") == host + ":25566")
check("address punctuation is not included",
      M.read_public_address("unused", log_lines=f"Join ({host}:25566).") == host + ":25566")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
