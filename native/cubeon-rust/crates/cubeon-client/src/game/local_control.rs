//! Explicit local diagnostic socket for native capture and parity probes.
//! Ordinary launches and saved upstream agent preferences never open it.
use super::Game;
use cubeon_client::{Result, control};

impl Game<'_> {
    pub(super) fn start_local_control(&mut self) -> Result<()> {
        if let Some(path) = &self.options.control {
            let server = control::Server::start(path)
                .map_err(|e| format!("control socket {}: {e}", path.display()))?;
            log::info!("Cubeon: diagnostic socket {}", server.path().display());
            self.control = Some(server);
        }
        Ok(())
    }
}
