//! Blocks and items as the client knows them, below gameplay: block facts
//! (`blocks`), item stacks and definitions (`items`), their data components
//! (`item_data`), enchantments, cooldowns, bundles and item stacks in NBT.
//! cubeon-client re-exports each module under its old path
//! (`cubeon_client::items`, ...).
#![forbid(unsafe_code)]
pub mod banner_layer;
pub mod blocks;
pub mod bundle;
pub mod content_namespaces;
pub mod cooldowns;
pub mod enchant;
pub mod firework;
pub mod flowers;
pub mod item_data;
pub mod item_nbt;
pub mod items;
pub mod random_sequences;
pub mod recipe_filters;
pub mod use_animation;
pub use cubeon_client_core::Result;
