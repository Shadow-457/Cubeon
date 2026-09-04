import os
import socket
import sys
import tempfile
import types
sys.modules.setdefault("minecraft_launcher_lib", types.SimpleNamespace(
    utils=types.SimpleNamespace(get_minecraft_directory=lambda: "/tmp/cubeon-test-mc")
))
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import p2p


def main():
    with tempfile.TemporaryDirectory() as td:
        p2p.SESSIONS_DIR = td
        original = os.path.join(td, "extra.jar")
        disabled = original + ".disabled"
        linked = os.path.join(td, "hostmod.jar")
        open(original, "wb").write(b"local")
        open(linked, "wb").write(b"host")
        p2p.record_session_links("room1", "1.21.1", "fabric", [linked],
                                 [{"original": original, "disabled": disabled}])
        os.rename(original, disabled)
        p2p.teardown("room1")
        assert os.path.exists(original)
        assert not os.path.exists(disabled)
        assert not os.path.exists(linked)
        assert not os.path.exists(os.path.join(td, "room1.json"))
    print("p2p session cleanup: PASS")

if __name__ == "__main__":
    main()
