//! Movable Fabric overlays with live native readings and measured drag bounds.
use super::{Game, Screen, companion::FEATURES};
use cubeon_client::{
    brewing,
    hud::{HudBatch, rgba},
    text::Text,
};
use cubeon_client_render::cubeon_ui::{self as art, Canvas};
use winit::{event::MouseButton, keyboard::KeyCode};
impl Game<'_> {
    pub(super) fn cubeon_hud(&mut self, batch: &mut HudBatch, editing: bool) {
        if self.companion.enabled && self.title.is_none() && self.screen == Screen::Paused {
            cubeon_client::ui::button(
                batch,
                &self.gui.atlas,
                batch.width - 108.,
                8.,
                100.,
                20.,
                &Text::literal("Client"),
                true,
                art::contains(self.cursor, [batch.width - 108., 8., 100., 20.]),
            );
            return;
        }
        if !self.companion.enabled
            || self.title.is_some()
            || self.player.is_none()
            || (!editing && (self.ui.hide_gui || self.screen != Screen::Playing))
        {
            return;
        }
        let active: [bool; 13] = std::array::from_fn(|i| editing || self.companion.enabled(i));
        let mut labels: [Vec<String>; 13] = Default::default();
        if active[0] {
            labels[0].push(format!(
                "{:.0} FPS",
                1000. / self.companion.frame_ms.max(0.1)
            ));
        }
        if active[3] {
            labels[3].push(
                self.cubeon_ping()
                    .map(|v| format!("Ping: {v} ms"))
                    .unwrap_or_else(|| "Ping: --".into()),
            );
        }
        if active[4] {
            labels[4] = vec![
                format!("LMB: {} CPS", self.companion.clicks[0].len()),
                format!("RMB: {} CPS", self.companion.clicks[1].len()),
            ];
        }
        if active[5] || active[11] {
            let minutes = (self.world.day_time + 6000).rem_euclid(24000) * 60 / 1000;
            let time = format!("{:02}:{:02}", minutes / 60, minutes % 60);
            if active[5] {
                labels[5].push(if self.companion.boolean("worldClock", false) {
                    time.clone()
                } else {
                    chrono::Local::now().format("%H:%M:%S").to_string()
                });
            }
            if active[11] {
                labels[11].push(format!(
                    "Day {}   {time}",
                    self.world.day_time.div_euclid(24000)
                ));
            }
        }
        if active[6] {
            labels[6] = vec![
                self.companion
                    .bridge
                    .snapshot()
                    .memory_mib
                    .map(|m| format!("RAM {m} MiB"))
                    .unwrap_or_else(|| "RAM —".into()),
                if self.gpu_utilization.is_finite() && self.gpu_utilization > 0. {
                    format!("GPU frame: {:.0}%", self.gpu_utilization.clamp(0., 100.))
                } else {
                    "GPU frame: —".into()
                },
            ];
        }
        if let Some(p) = &self.player {
            if active[8] {
                labels[8] = vec![
                    format!("X {:.1}   Y {:.1}", p.position.x, p.position.y),
                    format!("Z {:.1}", p.position.z),
                ];
            }
            let (x, y, z) = (
                p.position.x.floor() as i32,
                p.position.y.floor() as i32,
                p.position.z.floor() as i32,
            );
            if active[10] {
                labels[10].push(
                    self.world
                        .chunks
                        .get(&(x >> 4, z >> 4))
                        .map(|c| {
                            world_biomes!(self)
                                .get(c.biome(x, y, z))
                                .name
                                .to_string()
                                .replace("minecraft:", "")
                                .replace('_', " ")
                        })
                        .unwrap_or_else(|| "—".into()),
                );
            }
            if active[11] {
                let light = self.world.light(x, y, z);
                labels[11].push(format!("Block {}   Sky {}", light & 15, light >> 4));
            }
        }
        if active[9] {
            labels[9].push(format!(
                "{}  {}°",
                ["S", "SW", "W", "NW", "N", "NE", "E", "SE"]
                    [((self.yaw / 45.).round() as i32).rem_euclid(8) as usize],
                ((self.yaw + 180.).round() as i32).rem_euclid(360)
            ));
        }
        if active[12] {
            labels[12].push(format!(
                "Combo {}",
                if editing { 3 } else { self.companion.combo }
            ));
        }
        let effects = if active[7] {
            self.potions
                .effects
                .list
                .iter()
                .filter(|e| e.visible)
                .take(6)
                .cloned()
                .collect::<Vec<_>>()
        } else {
            Vec::new()
        };
        let effect_text: Vec<_> = effects
            .iter()
            .map(|e| {
                let mut name = self
                    .pack
                    .names
                    .display_get(&cubeon_client_core::potions::description_id(e.id))
                    .unwrap_or_else(|| e.id.replace('_', " "));
                if e.amplifier > 0 {
                    name.push_str(&format!(" {}", e.amplifier + 1));
                }
                (
                    name,
                    if e.duration < 0 {
                        "∞".into()
                    } else {
                        brewing::format_tick_duration(e.duration, self.clock.rate())
                    },
                )
            })
            .collect();
        self.companion.bounds = [[0.; 4]; 13];
        for i in 0..13 {
            if !active[i]
                || (!editing
                    && ((i == 7 && effects.is_empty()) || (i == 12 && self.companion.combo == 0)))
            {
                continue;
            }
            let mut w = labels[i]
                .iter()
                .map(|t| HudBatch::text_width(&self.gui.atlas, t) + 4.)
                .fold(8., f32::max);
            let mut h = if labels[i].len() > 1 { 24. } else { 12. };
            if i >= 5 {
                w = w.min(FEATURES[i].2);
            }
            if i == 1 {
                w = 64.;
                h = 76.;
            }
            if i == 2 {
                w = 44.;
                h = 64.;
            }
            if i == 7 {
                w = effect_text
                    .iter()
                    .map(|(n, t)| {
                        24. + HudBatch::text_width(&self.gui.atlas, n)
                            + HudBatch::text_width(&self.gui.atlas, t)
                    })
                    .fold(
                        HudBatch::text_width(&self.gui.atlas, "No active effects") + 4.,
                        f32::max,
                    )
                    .min(150.);
                h = (effects.len() as f32 * 12. + 2.).max(12.);
            }
            let (nx, ny, scale) = self.companion.position(i);
            let (x, y) = (
                nx * (batch.width - w * scale).max(0.),
                ny * (batch.height - h * scale).max(0.),
            );
            self.companion.bounds[i] = [x, y, w * scale, h * scale];
            let start = batch.vertices.len();
            if i != 1 && i != 2 {
                batch.fill(&self.gui.atlas, x, y, w, h, rgba(0, 0, 0, 136));
            }
            if i == 1 {
                for (key, label, dx, dy) in [
                    (KeyCode::KeyW, "W", 22., 0.),
                    (KeyCode::KeyA, "A", 0., 22.),
                    (KeyCode::KeyS, "S", 22., 22.),
                    (KeyCode::KeyD, "D", 44., 22.),
                ] {
                    key_box(
                        batch,
                        &self.gui.atlas,
                        [x + dx, y + dy, 20., 20.],
                        label,
                        editing || self.keys.contains(&key),
                    );
                }
                key_box(
                    batch,
                    &self.gui.atlas,
                    [x, y + 44., 31., 20.],
                    "LMB",
                    editing || self.left,
                );
                key_box(
                    batch,
                    &self.gui.atlas,
                    [x + 33., y + 44., 31., 20.],
                    "RMB",
                    editing || self.right,
                );
                key_box(
                    batch,
                    &self.gui.atlas,
                    [x, y + 66., 64., 10.],
                    "",
                    editing || self.keys.contains(&KeyCode::Space),
                );
            } else if i == 2 {
                let armor = self.armor.clone();
                let mut row = 0;
                for (slot, stack) in armor.iter().rev().enumerate() {
                    if self.companion.boolean(
                        [
                            "showArmorHelmet",
                            "showArmorChest",
                            "showArmorLegs",
                            "showArmorFeet",
                        ][slot],
                        true,
                    ) && let Some(stack) = stack
                    {
                        let max = self.items().get(&stack.item).map_or(0, |v| v.max_damage);
                        if max == 0 {
                            continue;
                        }
                        self.draw_item_model(batch, stack, x, y + row as f32 * 16.);
                        batch.text(
                            &self.gui.atlas,
                            &max.saturating_sub(stack.damage).to_string(),
                            x + 19.,
                            y + row as f32 * 16. + 4.,
                            u32::MAX,
                            true,
                        );
                        row += 1;
                    }
                }
                if editing && row == 0 {
                    batch.text(&self.gui.atlas, "Armor", x + 2., y + 2., u32::MAX, true);
                }
            } else if i == 7 {
                if effects.is_empty() {
                    batch.text(
                        &self.gui.atlas,
                        "No active effects",
                        x + 2.,
                        y + 1.,
                        u32::MAX,
                        true,
                    );
                }
                for (row, (effect, (name, timer))) in effects.iter().zip(&effect_text).enumerate() {
                    let top = y + 1. + row as f32 * 12.;
                    let mut sprite = String::new();
                    cubeon_client_core::potions::push_sprite(&mut sprite, effect.id);
                    if let Some(r) = self.gui.atlas.sprite_or_missing(&sprite) {
                        batch.rect_uv(x + 2., top, 10., 10., r, u32::MAX);
                    }
                    let tw = HudBatch::text_width(&self.gui.atlas, timer);
                    batch.text(
                        &self.gui.atlas,
                        &art::fit(&self.gui.atlas, name, (w - tw - 24.).max(0.)),
                        x + 14.,
                        top,
                        u32::MAX,
                        true,
                    );
                    batch.text(&self.gui.atlas, timer, x + w - 2. - tw, top, u32::MAX, true);
                }
            } else {
                for (line, text) in labels[i].iter().enumerate() {
                    let color = if i == 3 {
                        self.cubeon_ping()
                            .map(|v| {
                                if v <= 60 {
                                    0xff57c96b
                                } else if v <= 130 {
                                    0xffffd75f
                                } else {
                                    0xffff5f5f
                                }
                            })
                            .unwrap_or(0xff6a6a70)
                    } else {
                        u32::MAX
                    };
                    batch.text(
                        &self.gui.atlas,
                        &art::fit(&self.gui.atlas, text, w - 4.),
                        x + 2.,
                        y + 1. + line as f32 * 11.,
                        art::native_color(color),
                        true,
                    );
                }
            }
            for v in &mut batch.vertices[start..] {
                v.pos[0] = x + (v.pos[0] - x) * scale;
                v.pos[1] = y + (v.pos[1] - y) * scale;
            }
            if editing {
                let color = art::native_color(if self.companion.selected == Some(i) {
                    self.companion.palette.accent()
                } else {
                    self.companion.palette.border()
                });
                for r in [
                    [x, y, w * scale, 1.],
                    [x, y + h * scale - 1., w * scale, 1.],
                    [x, y, 1., h * scale],
                    [x + w * scale - 1., y, 1., h * scale],
                ] {
                    batch.fill(&self.gui.atlas, r[0], r[1], r[2], r[3], color);
                }
            }
        }
    }
    pub(super) fn cubeon_click_count(&mut self, button: MouseButton) {
        let i = match button {
            MouseButton::Left => 0,
            MouseButton::Right => 1,
            _ => return,
        };
        if self.companion.clicks[i].len() < 256 {
            self.companion.clicks[i].push_back(std::time::Instant::now());
        }
    }
    pub(super) fn cubeon_pause_click(&mut self) -> bool {
        let (w, _) = self.gui_size();
        if self.companion.enabled && art::contains(self.cursor, [w - 108., 8., 100., 20.]) {
            self.cubeon_open(0);
            true
        } else {
            false
        }
    }
}
fn key_box(
    batch: &mut HudBatch,
    atlas: &cubeon_client::hud::HudAtlas,
    r: [f32; 4],
    label: &str,
    held: bool,
) {
    let mut ui = Canvas {
        batch,
        atlas,
        palette: Default::default(),
        fade: 1.,
    };
    ui.fill(r, if held { 0xe0245b2a } else { 0xc814161b });
    let color = if held { 0xff57c96b } else { 0xff33363c };
    for rect in [
        [r[0], r[1], r[2], 1.],
        [r[0], r[1] + r[3] - 1., r[2], 1.],
        [r[0], r[1], 1., r[3]],
        [r[0] + r[2] - 1., r[1], 1., r[3]],
    ] {
        ui.fill(rect, color);
    }
    if label.is_empty() {
        ui.fill(
            [r[0] + r[2] / 2. - 5., r[1] + r[3] / 2., 10., 1.],
            if held { u32::MAX } else { 0xff8c8c92 },
        );
    } else {
        ui.batch.text(
            atlas,
            label,
            r[0] + (r[2] - HudBatch::text_width(atlas, label)) / 2.,
            r[1] + (r[3] - 9.) / 2.,
            art::native_color(if held { u32::MAX } else { 0xff8c8c92 }),
            true,
        );
    }
}
