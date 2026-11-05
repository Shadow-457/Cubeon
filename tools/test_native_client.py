"""Native launcher setup; --compiled exercises real appearance and bridge workers."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
BUILD_ENV = dict(os.environ)
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import native_client, paths

COMPILED = r'''
use cubeon_client_render::{cubeon_bridge::Bridge,cubeon_skins::{Service,Snapshot}};
use std::{path::PathBuf,time::{Duration,Instant}};
fn wait(mut condition:impl FnMut()->bool) {
    let until=Instant::now()+Duration::from_secs(15);
    while !condition() {assert!(Instant::now()<until,"Native worker timed out");std::thread::sleep(Duration::from_millis(50));}
}
fn appearance(service:&mut Service)->Snapshot {service.snapshot(vec![(1,"Fixture".into())]).clone()}
fn main() {
    let root=PathBuf::from(std::env::args().nth(1).unwrap());
    let mut skins=Service::new(root.clone());
    wait(||appearance(&mut skins).players.get(&1).is_some_and(|p|p.skin.is_some()&&p.cape.is_some()));
    let first=appearance(&mut skins);let first=first.players.get(&1).unwrap();
    assert!(first.slim,"Explicit slim model lost");
    assert_eq!(&*first.skin.as_ref().unwrap().rgba,std::fs::read(root.join("expected-skin.rgba")).unwrap());
    let public_cape=first.cape.as_ref().unwrap().location.clone();
    std::fs::copy(root.join("hidden.png"),root.join("capes/Fixture.png")).unwrap();
    wait(||appearance(&mut skins).players.get(&1).is_some_and(|p|p.cape.as_ref().is_some_and(|c|c.location!=public_cape)));
    let hidden=appearance(&mut skins);assert!(hidden.players[&1].cape.as_ref().unwrap().rgba.chunks(4).all(|p|p[3]==0),"Hidden cape fell through to public source");
    let path=root.join("config/cubeon-native-appearance.json");
    let value=std::fs::read_to_string(&path).unwrap().replace("\"enabled\": true","\"enabled\": false");std::fs::write(path,value).unwrap();
    wait(||appearance(&mut skins).players.is_empty());
    let mut bridge=Bridge::new();wait(||bridge.snapshot().up);
    bridge.context("a".repeat(64));bridge.chat("Peer&x".into());
    wait(||bridge.snapshot().chat["messages"].as_array().is_some_and(|m|!m.is_empty()) && bridge.snapshot().emotes["room"]=="a".repeat(64));
    let mut body=bridge.snapshot().friends.clone();body.as_object_mut().unwrap().clear();
    body["to"]="Peer&x".into();body["text"]="native fixture".into();
    assert!(bridge.action("/dm",body));
    wait(||root.join("sent.json").exists());
    bridge.chat(String::new());wait(||root.join("closed.json").exists());
    println!("Compiled native local/remote appearance, slim model, cape hiding, opt-out and authenticated friends/chat/emotes passed.");
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="native-client-check-") as temp:
        directory = Path(temp)
        cfg = {"username": "Fixture", "active_skin": "fixture.png", "manage_skin_mod": True}
        with patch("cubeon.skins.sync_local_skin_to_csl") as skin, patch("cubeon.capes.sync_local_cape_to_csl") as cape, \
                patch("cubeon.cosmetics.sync_to_game") as cosmetics, patch("cubeon.skins._active_skin_is_slim", return_value=True):
            env = native_client.prepare(cfg, temp, "Fixture")
            skin.assert_called_once_with(cfg)
            cape.assert_called_once_with(cfg)
            cosmetics.assert_called_once_with(cfg, temp)
        appearance_path = directory / "config/cubeon-native-appearance.json"
        appearance = json.loads(appearance_path.read_text())
        assert appearance["model"] == "slim" and appearance["username"] == "Fixture"
        assert appearance["localSkinDir"] == paths.CSL_LOCAL_SKINS_DIR
        assert Path(env["CUBEON_BRIDGE_FILE"]).name == "local_api.json"
        assert env["CUBEON_CLIENT_ENABLED"] == "1"
        cfg["client_mod_enabled"] = False
        with patch("cubeon.skins.sync_local_skin_to_csl"), patch("cubeon.capes.sync_local_cape_to_csl"), patch("cubeon.cosmetics.sync_to_game"):
            assert native_client.prepare(cfg, temp, "Fixture")["CUBEON_CLIENT_ENABLED"] == "0"
        appearance_path.write_text(json.dumps(appearance))
        assert not (directory / "mods").exists()
        if not args.compiled:
            print("Native appearance/companion launcher preparation passed.")
            return

        from PIL import Image
        for folder in ("skins", "capes", "elytras"):
            (directory / folder).mkdir()
        skin_image = Image.new("RGBA", (64, 64), (30, 160, 95, 255))
        skin_image.save(directory / "skins/Fixture.png")
        (directory / "expected-skin.rgba").write_bytes(skin_image.tobytes())
        Image.new("RGBA", (64, 32)).save(directory / "hidden.png")
        public = directory / "public.png"
        Image.new("RGBA", (64, 32), (150, 90, 30, 255)).save(public)
        cape_bytes = public.read_bytes()
        cape_id = hashlib.sha256(cape_bytes).hexdigest()
        token = "fixture_native_capability_0123456789"
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                if self.path.startswith("/skins/"):
                    self.reply({"textures": {"cape": cape_id}})
                elif self.path == "/textures/" + cape_id:
                    self.reply(cape_bytes)
                elif self.headers.get("X-Cubeon-Token") != token:
                    self.reply({"error": "unauthorized"}, 401)
                elif self.path == "/friends":
                    self.reply({"friends": [{"name": "Peer&x", "online": True}]})
                elif self.path == "/players":
                    self.reply({"players": []})
                elif self.path == "/emotes":
                    self.reply({"room": "a" * 64, "active": []})
                elif self.path == "/chat?friend=Peer%26x&after=0":
                    seen.append("chat")
                    self.reply({"messages": [{"seq": 1, "text": "fixture"}]})
                else:
                    self.reply({"error": "unknown"}, 404)

            def do_POST(self):
                assert self.headers.get("X-Cubeon-Token") == token
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path in ("/dm", "/chatclose"):
                    (directory / ("sent.json" if self.path == "/dm" else "closed.json")).write_text(json.dumps(body))
                self.reply({"ok": True})

            def reply(self, body, status=200):
                payload = body if isinstance(body, bytes) else json.dumps(body).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            appearance.update(localSkinDir=str(directory / "skins"), localCapeDir=str(directory / "capes"),
                              localElytraDir=str(directory / "elytras"), publicRoot=f"http://127.0.0.1:{server.server_port}")
            appearance_path.write_text(json.dumps(appearance))
            credentials = directory / "bridge.json"
            credentials.write_text(json.dumps({"port": server.server_port, "token": token}))
            dependencies = ROOT / "native/cubeon-rust/target/fast/deps"
            renderer = max(dependencies.glob("libcubeon_client_render-*.rlib"), key=lambda p: p.stat().st_mtime)
            source = directory / "native.rs"
            source.write_text(COMPILED)
            executable = directory / ("native.exe" if os.name == "nt" else "native")
            subprocess.run([shutil.which("rustc"), "--edition=2024", str(source), "--extern", f"cubeon_client_render={renderer}",
                "-L", f"dependency={dependencies}", "-o", str(executable)], env=BUILD_ENV, check=True)
            subprocess.run([str(executable), temp], env={**os.environ, "CUBEON_BRIDGE_FILE": str(credentials)}, check=True, timeout=60)
            assert json.loads((directory / "sent.json").read_text()) == {"to": "Peer&x", "text": "native fixture"}
            assert json.loads((directory / "closed.json").read_text()) == {"name": "Peer&x"}
            assert "chat" in seen
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
