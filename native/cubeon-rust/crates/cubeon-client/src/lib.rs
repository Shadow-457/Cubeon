//! Gameplay and startup, above the reusable client library.
// No `#![recursion_limit]` or other inner attribute cubeon-mixins doesn't know here: the
// launcher's cubeon-mixins then rejects every native mod targeting this crate (#8169).
#![forbid(unsafe_code)]
extern crate self as cubeon_client;
pub use cubeon_client_lib::*;
pub mod entry;
pub mod game;
pub mod mod_api;
