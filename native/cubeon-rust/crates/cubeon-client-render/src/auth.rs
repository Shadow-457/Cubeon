//! Cubeon offline-only compatibility surface. No credentials, sessions or account HTTP.
use std::{path::Path, sync::Arc, time::{SystemTime, UNIX_EPOCH}};
#[derive(Debug)]
pub struct AuthSession { pub name: String, pub uuid: u128, pub xuid: Option<String> }
impl AuthSession {
    pub fn new(name: &str, uuid: u128, _: &str) -> Self { Self { name: name.into(), uuid, xuid: None } }
    pub fn parse(_: &str) -> Result<Self, String> { Err("Cubeon Rust uses local profiles".into()) }
    pub fn load(_: &Path) -> Result<Self, String> { Err("Cubeon Rust uses local profiles".into()) }
    pub fn expired(&self) -> bool { true }
}
pub fn parse_uuid(text: &str) -> Option<u128> {
    let hex: String = text.chars().filter(|c| *c != '-').collect();
    (hex.len() == 32).then(|| u128::from_str_radix(&hex, 16).ok()).flatten()
}
pub fn set_current(_: AuthSession) {}
pub fn current() -> Option<Arc<AuthSession>> { None }
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum JoinError { Unavailable, InvalidSession, InsufficientPrivileges, Banned, Other(String) }
impl JoinError {
    pub fn reason(&self) -> Result<&'static str, &str> { Ok("disconnect.loginFailedInfo.invalidSession") }
}
pub fn discovery() -> Result<Arc<serde_json::Value>, JoinError> { Err(JoinError::Unavailable) }
pub fn endpoint(_: &serde_json::Value, _: &str, _: &str) -> Option<String> { None }
pub fn fetch_account_status(_: &AuthSession) -> crate::ban_notice::AccountStatus { Default::default() }
pub fn join_server(_: &AuthSession, _: &str) -> Result<(), JoinError> { Err(JoinError::InvalidSession) }
#[derive(Debug)]
pub struct ChatKeyPair {
    pub private: cubeon_protocol::rsa::RsaPrivateKey,
    pub public: cubeon_protocol::secure_chat::ProfileKey,
    pub refreshed_after: i64,
}
impl ChatKeyPair { pub fn due_refresh(&self, _: i64) -> bool { false } }
pub fn now_millis() -> i64 { SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_millis() as i64) }
pub fn prepare_chat_keys(_: bool) {}
pub fn prepare_chat_keys_for(_: Arc<AuthSession>, _: bool) {}
pub fn chat_keys() -> Option<Arc<ChatKeyPair>> { None }
pub fn chat_keys_for(_: u128) -> Option<Arc<ChatKeyPair>> { None }
pub fn own_textures(_: &AuthSession) -> Option<crate::skins::Textures> { None }
#[derive(Debug, PartialEq)]
pub struct JoinedProfile { pub uuid: u128, pub properties: Vec<cubeon_protocol::packets::login::Property> }
pub fn has_joined(_: &str, _: &str, _: Option<std::net::IpAddr>) -> Result<Option<JoinedProfile>, JoinError> { Err(JoinError::InvalidSession) }
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn credentials_cannot_activate_an_account() {
        assert!(AuthSession::parse("{}").is_err());
        set_current(AuthSession::new("Player", 42, "ignored"));
        assert!(current().is_none());
        assert!(discovery().is_err());
        assert!(chat_keys_for(42).is_none());
    }
}

/// Cubeon's persistent local identity applies only to its own memory connection.
/// External offline servers retain the standard name-derived UUID.
pub fn local_uuid(name: &str) -> u128 {
    local_uuid_from(name, std::env::var("CUBEON_RUST_PLAYER_NAME").ok().as_deref(),
                    std::env::var("CUBEON_RUST_PLAYER_UUID").ok().as_deref())
}
fn local_uuid_from(name: &str, local_name: Option<&str>, id: Option<&str>) -> u128 {
    if local_name == Some(name) {
        if let Some(uuid) = id.and_then(parse_uuid) { return uuid; }
    }
    cubeon_protocol::crypto::offline_uuid(name)
}
#[cfg(test)]
mod identity_tests {
    use super::*;
    #[test] fn local_identity_survives_name_changes_and_never_applies_to_guests() {
        let id = "01234567-89ab-cdef-0123-456789abcdef";
        assert_eq!(local_uuid_from("Before", Some("Before"), Some(id)),
                   local_uuid_from("After", Some("After"), Some(id)));
        assert_eq!(local_uuid_from("Guest", Some("After"), Some(id)),
                   cubeon_protocol::crypto::offline_uuid("Guest"));
        assert_eq!(local_uuid_from("After", Some("After"), Some("bad")),
                   cubeon_protocol::crypto::offline_uuid("After"));
    }
}
