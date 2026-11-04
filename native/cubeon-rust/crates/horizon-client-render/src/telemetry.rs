//! No telemetry collection/outbox in Cubeon Rust. Local crash logs are separate.
use std::path::Path;
use horizon_telemetry::payload::{Perf, Settings, System};
#[derive(Clone, Debug, Default)]
pub struct Gpu { pub name: String, pub vendor: String, pub kind: String, pub driver: String, pub backend: String }
pub fn mark_start() {}
pub fn mark_core_ready() {}
pub fn mark_rest_ready() {}
pub fn set_gpu(_: Gpu) {}
pub fn set_display(_: u32, _: u32, _: u32, _: f64) {}
pub fn monitor(window: &winit::window::Window) -> Option<winit::monitor::MonitorHandle> { window.current_monitor() }
pub fn note_display(_: &winit::window::Window) {}
pub fn gpu_kind(t: &str) -> &'static str { match t { "DiscreteGpu" => "discrete", "IntegratedGpu" => "integrated", _ => "other" } }
pub fn system() -> System { System::detect() }
pub fn version() -> String { "Cubeon Rust 26.3-beta.1".into() }
pub fn keep_crash(_: &Path, _: &crate::crash::Report) {}
pub fn keep_benchmark(_: &Path, _: &horizon_bench::Report) {}
#[derive(Default)]
pub struct Session;
impl Session {
    pub fn title_shown(&mut self) {}
    pub fn world_opening(&mut self) {}
    pub fn cancel_world_opening(&mut self) {}
    pub fn frame(&mut self, _: f32, _: &[crate::spans::Span]) {}
    pub fn tick(&mut self, _: f32) {}
    pub fn summary(&self, _: Settings) -> Option<Perf> { None }
    pub fn finish(&mut self, _: &Path, _: Settings) {}
}
