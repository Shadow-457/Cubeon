//! Native companion overlays use the same saved positions and toggles as Java.
use super::{Game, Screen, companion::FEATURES};
use cubeon_client::hud::{HudBatch, rgba};
use winit::{event::MouseButton, keyboard::KeyCode};

impl Game<'_> {
    pub(super) fn cubeon_hud(&mut self, batch: &mut HudBatch, editing: bool) {
        if self.companion.enabled && self.title.is_none() && self.screen == Screen::Paused {
            let rect = [batch.width - 108., 8., 100., 20.];
            cubeon_client::ui::button(
                batch,
                &self.gui.atlas,
                rect[0],
                rect[1],
                rect[2],
                rect[3],
                &cubeon_client::text::Text::literal("Client"),
                true,
                cubeon_client::ui::hovered(self.cursor, rect[0], rect[1], rect[2], rect[3]),
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
        let mut labels = vec![String::new(); FEATURES.len()];
        labels[0] = format!("{:.0} FPS", 1000. / self.companion.frame_ms.max(0.1));
        labels[3] = self
            .cubeon_ping()
            .map(|ping| format!("{ping} ms"))
            .unwrap_or_else(|| "Local world".into());
        labels[4] = format!(
            "{} | {} CPS",
            self.companion.clicks[0].len(),
            self.companion.clicks[1].len()
        );
        labels[5] = chrono::Local::now().format("%H:%M:%S").to_string();
        labels[6] = format!("Rust · {:.1} ms/frame", self.companion.frame_ms);
        labels[7] = if self.potions.effects.list.is_empty() {
            "No active effects".into()
        } else {
            self.potions
                .effects
                .list
                .iter()
                .take(6)
                .map(|effect| effect.id.replace('_', " "))
                .collect::<Vec<_>>()
                .join("\n")
        };
        if let Some(p) = &self.player {
            labels[8] = format!(
                "XYZ {:.0} {:.0} {:.0}",
                p.position.x, p.position.y, p.position.z
            );
            let [x, y, z] = [
                p.position.x.floor() as i32,
                p.position.y.floor() as i32,
                p.position.z.floor() as i32,
            ];
            if let Some(chunk) = self.world.chunks.get(&(x >> 4, z >> 4)) {
                labels[10] = world_biomes!(self)
                    .get(chunk.biome(x, y, z))
                    .name
                    .to_string()
                    .replace("minecraft:", "")
                    .replace('_', " ");
            }
        }
        labels[9] = ["South", "West", "North", "East"]
            [((self.yaw / 90. + 0.5).floor() as i32).rem_euclid(4) as usize]
            .into();
        labels[11] = format!(
            "Day {} · {:02}:{:02}",
            self.world.game_time.div_euclid(24000) + 1,
            (self.world.day_time.rem_euclid(24000) / 1000 + 6) % 24,
            self.world.day_time.rem_euclid(1000) * 60 / 1000
        );
        labels[12] = format!("{} Combo", self.companion.combo);
        for (i, feature) in FEATURES.iter().enumerate() {
            if !editing && !self.companion.enabled(i) {
                continue;
            }
            let (x, y, scale) = self.companion.position(i);
            let (w, h) = (feature.2 * scale, feature.3 * scale);
            let (x, y) = (
                x * (batch.width - w).max(0.),
                y * (batch.height - h).max(0.),
            );
            let start = batch.vertices.len();
            batch.fill(
                &self.gui.atlas,
                x,
                y,
                feature.2,
                feature.3,
                rgba(9, 19, 22, 180),
            );
            if i == 1 {
                for (key, label, dx, dy) in [
                    (KeyCode::KeyW, "W", 22., 2.),
                    (KeyCode::KeyA, "A", 2., 22.),
                    (KeyCode::KeyS, "S", 22., 22.),
                    (KeyCode::KeyD, "D", 42., 22.),
                    (KeyCode::Space, "Space", 2., 44.),
                ] {
                    batch.fill(
                        &self.gui.atlas,
                        x + dx,
                        y + dy,
                        if key == KeyCode::Space { 60. } else { 18. },
                        18.,
                        rgba(
                            84,
                            175,
                            141,
                            if self.physical_keys.contains(&key) {
                                230
                            } else {
                                60
                            },
                        ),
                    );
                    batch.text(
                        &self.gui.atlas,
                        label,
                        x + dx + 3.,
                        y + dy + 5.,
                        u32::MAX,
                        false,
                    );
                }
            } else if i == 2 {
                let armor = self.armor.clone();
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
                        self.draw_item_model(batch, stack, x + slot as f32 * 23. + 2., y + 3.);
                        self.draw_item_decorations(
                            batch,
                            stack,
                            x + slot as f32 * 23. + 2.,
                            y + 3.,
                            None,
                        );
                    }
                }
            } else {
                for (line, text) in labels[i].lines().enumerate() {
                    batch.text(
                        &self.gui.atlas,
                        text,
                        x + 3.,
                        y + 2. + line as f32 * 10.,
                        u32::MAX,
                        false,
                    );
                }
            }
            for vertex in &mut batch.vertices[start..] {
                vertex.pos[0] = x + (vertex.pos[0] - x) * scale;
                vertex.pos[1] = y + (vertex.pos[1] - y) * scale;
            }
            if editing {
                batch.fill(&self.gui.atlas, x, y, w, 1., rgba(125, 225, 191, 255));
                if self.companion.selected == Some(i) {
                    batch.text(
                        &self.gui.atlas,
                        "Drag to move · scroll to resize · right click to toggle",
                        8.,
                        batch.height - 113.,
                        u32::MAX,
                        true,
                    );
                }
            }
        }
        if !editing
            && self.companion.boolean("showEnemyHealth", false)
            && let Some((index, distance)) = self.mob_hit()
            && distance <= self.entity_reach
        {
            let mob = &self.mobs[index];
            if mob.health > 0. {
                let label = format!(
                    "{} · {:.0} HP",
                    mob.kind.id.replace("minecraft:", "").replace('_', " "),
                    mob.health
                );
                let width = HudBatch::text_width(&self.gui.atlas, &label);
                let x = (batch.width - width) / 2.;
                batch.fill(
                    &self.gui.atlas,
                    x - 3.,
                    batch.height / 2. + 17.,
                    width + 6.,
                    14.,
                    rgba(9, 19, 22, 200),
                );
                batch.text(
                    &self.gui.atlas,
                    &label,
                    x,
                    batch.height / 2. + 20.,
                    u32::MAX,
                    true,
                );
            }
        }
    }

    pub(super) fn cubeon_click_count(&mut self, button: MouseButton) {
        let index = match button {
            MouseButton::Left => 0,
            MouseButton::Right => 1,
            _ => return,
        };
        if self.companion.clicks[index].len() < 256 {
            self.companion.clicks[index].push_back(std::time::Instant::now());
        }
    }

    pub(super) fn cubeon_pause_click(&mut self) -> bool {
        let (w, _) = self.gui_size();
        if self.companion.enabled
            && cubeon_client::ui::hovered(self.cursor, w - 108., 8., 100., 20.)
        {
            self.companion.open = true;
            self.companion.tab = 0;
            self.screen = Screen::Friends;
            return true;
        }
        false
    }
}
