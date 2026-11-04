//! This beta has no launcher account/session integration.
use cubeon_client::auth::AuthSession;
use std::sync::Arc;
pub(super) fn accounts() -> Vec<Arc<AuthSession>> { Vec::new() }
pub(super) fn unavailable() -> Vec<String> { Vec::new() }
pub(in crate::game) fn read_now() {}
