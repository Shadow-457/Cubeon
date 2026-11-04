//! Cubeon: native Rust client for Minecraft Java Edition 26.3 gameplay.
#![forbid(unsafe_code)]

#[cfg(not(any(feature = "system-allocator", feature = "alloc-census")))]
#[global_allocator]
static ALLOCATOR: cubeon_threads::Allocator = cubeon_threads::ALLOCATOR;
#[cfg(all(feature = "alloc-census", not(feature = "system-allocator")))]
#[global_allocator]
static ALLOCATOR: cubeon_threads::CensusAllocator = cubeon_threads::CensusAllocator;

/// The mod API level this game serves, kept in the program for the launcher
/// to read without running it (`cubeon_mods::api_level::MARK`). `main`
/// reads it, so the linker keeps it.
static MOD_API_LEVEL: [u8; 27] = cubeon_mods::api_level::MARK;

fn main() {
    std::hint::black_box(&MOD_API_LEVEL);
    cubeon_client::entry::main();
}
