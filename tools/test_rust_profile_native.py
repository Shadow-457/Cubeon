"""Exercise the actual compiled Rust profile API without linking a second game test suite."""
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = ROOT / "native/cubeon-rust/target/fast/deps"


def main():
    libraries = list(DEPENDENCIES.glob("libcubeon_client_render-*.rlib"))
    library = max(libraries, key=lambda p: p.stat().st_mtime)
    with tempfile.TemporaryDirectory(prefix="cubeon-rust-profile-") as temp:
        folder = Path(temp)
        source = folder / "profile.rs"
        source.write_text('''use cubeon_client_render::auth::*;
fn main() {
    assert!(AuthSession::parse("{}").is_err());
    let session = AuthSession::new("Fixture", 42, "discarded fixture token");
    assert!(join_server(&session, "fixture").is_err());
    set_current(session);
    assert!(current().is_none());
    assert!(discovery().is_err());
    assert!(chat_keys().is_none());
    let name = std::env::var("CUBEON_RUST_PLAYER_NAME").unwrap();
    let expected = parse_uuid("01234567-89ab-cdef-0123-456789abcdef").unwrap();
    assert_eq!(local_uuid(&name), expected);
    assert_ne!(local_uuid("UnrelatedGuest"), expected);
    println!("Compiled offline profile and persistent identity checks passed for {name}");
}
''')
        executable = folder / ("profile.exe" if os.name == "nt" else "profile")
        subprocess.run(["rustc", "--edition=2024", str(source), "--extern",
                        f"cubeon_client_render={library}", "-L", f"dependency={DEPENDENCIES}",
                        "-o", str(executable)], check=True)
        env = {**os.environ, "HOME": str(folder), "USERPROFILE": str(folder),
               "CUBEON_RUST_PLAYER_UUID": "01234567-89ab-cdef-0123-456789abcdef"}
        for name in ("BeforeRename", "AfterRename"):
            env["CUBEON_RUST_PLAYER_NAME"] = name
            subprocess.run([str(executable)], env=env, check=True)


if __name__ == "__main__":
    main()
