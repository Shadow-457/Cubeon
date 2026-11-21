//! The shared ten-emote catalogue and Fabric's glass wheel/favorites editor.
use super::{Game, companion::Companion};
use cubeon_client::{cubeon_emotes as emotes, hud::HudBatch, widgets};
use cubeon_client_render::cubeon_ui::{self as art, Canvas};
use serde_json::{Value, json};
use winit::keyboard::KeyCode;

const STOP: i32 = -1;
const NONE: i32 = -2;
const TOGGLE: i32 = -3;
const EDIT: i32 = -4;
const DONE: i32 = -5;
const DEFAULTS: [&str; 8] = [
    "wave",
    "dance",
    "bow",
    "salute",
    "shrug",
    "point",
    "clap",
    "celebrate",
];
impl Companion {
    pub fn favorites(&self) -> Vec<String> {
        let mut result = Vec::new();
        if let Some(values) = self.config["emoteFavorites"].as_array() {
            for name in values.iter().filter_map(Value::as_str) {
                if emotes::NAMES.contains(&name) && !result.iter().any(|s| s == name) {
                    result.push(name.to_owned());
                }
                if result.len() == 8 {
                    break;
                }
            }
        }
        if result.is_empty() {
            result = DEFAULTS.iter().map(|n| (*n).into()).collect();
        }
        result
    }
}
fn layout(w: f32, h: f32) -> (f32, f32, f32, f32, f32) {
    (
        w / 2.,
        h / 2. - 5.,
        ((w - 24.) / 2.).min((h - 92.) / 2.).clamp(24., 116.),
        ((w - 32.) / 2.).min(148.),
        ((h - 94.) / 5.).min(32.).max(12.),
    )
}
fn center_width(radius: f32) -> f32 {
    (2. * ((radius * 0.36).powi(2) - 400.).max(0.).sqrt().floor() - 4.).clamp(28., 72.)
}
impl Game<'_> {
    pub(super) fn cubeon_emotes_frame(&mut self, value: &Value, eligible: bool) {
        if !self.companion.boolean("showEmotes", true) || self.player.is_none() {
            emotes::clear();
            return;
        }
        let mut live = std::collections::HashSet::new();
        if let Some(active) = value["active"].as_array() {
            for event in active.iter().take(128) {
                let uuid = event["uuid"].as_str().unwrap_or("").replace('-', "");
                let Ok(uuid) = u128::from_str_radix(&uuid, 16) else {
                    continue;
                };
                let name = event["username"].as_str().unwrap_or("");
                let emote = event["emote"].as_str().unwrap_or("");
                let serial = event["serial"].as_i64().unwrap_or(-1);
                let age = event["age"].as_f64().unwrap_or(f64::NAN) as f32;
                if serial < 0 || !age.is_finite() || age < 0. || !emotes::NAMES.contains(&emote) {
                    continue;
                }
                if let Some(r) = &self.remote
                    && uuid == r.profile()
                    && name.eq_ignore_ascii_case(&self.options.player_name())
                {
                    emotes::event(0, emote, serial, age);
                    live.insert(0);
                }
                for player in self
                    .mobs
                    .iter()
                    .filter(|m| &*m.kind.id == "minecraft:player")
                {
                    if self.remote_player_uuid(player.id) == Some(uuid)
                        && self
                            .remote_player_name(player.id)
                            .is_some_and(|n| n.eq_ignore_ascii_case(name))
                    {
                        emotes::event(player.id, emote, serial, age);
                        live.insert(player.id);
                    }
                }
            }
        }
        emotes::retain_live(&live);
        if emotes::playing(0)
            && (eligible
                && self.player.as_ref().is_some_and(|p| {
                    p.velocity.x * p.velocity.x + p.velocity.z * p.velocity.z > 0.0004
                })
                || self.left
                || self.right
                || self.keys.contains(&KeyCode::Space)
                || self.riding.is_some())
        {
            self.cubeon_play_emote("stop");
        }
    }
    pub(super) fn cubeon_play_emote(&mut self, name: &str) {
        let Some(uuid) = self.remote.as_ref().map(|r| r.profile()) else {
            return;
        };
        self.companion.emote_serial = if self.companion.emote_serial >= i32::MAX as i64 {
            1
        } else {
            self.companion.emote_serial + 1
        };
        let serial = self.companion.emote_serial;
        emotes::local(0, name, serial);
        self.companion.bridge.action(
            "/emote",
            json!({"uuid":format!("{uuid:032x}"),"emote":name,"serial":serial}),
        );
    }
    fn wheel_hit(&self) -> i32 {
        let (w, h) = self.gui_size();
        let (cx, cy, r, cw, rh) = layout(w, h);
        let (mx, my) = self.cursor;
        let c = &self.companion;
        if c.tab == 8 {
            let top = cy - rh * 2.5;
            for i in 0..10 {
                if art::contains(
                    (mx, my),
                    [
                        cx - cw + (i % 2) as f32 * cw + 3.,
                        top + (i / 2) as f32 * rh + 2.,
                        cw - 6.,
                        rh - 4.,
                    ],
                ) {
                    return i;
                }
            }
            return if art::contains((mx, my), [cx - 65., top + rh * 5. + 20., 130., 20.]) {
                DONE
            } else {
                NONE
            };
        }
        let width = center_width(r);
        if art::contains((mx, my), [cx - width / 2., cy - 20., width, 12.]) {
            return TOGGLE;
        }
        if art::contains((mx, my), [cx - width / 2., cy + 8., width, 12.]) {
            return EDIT;
        }
        let (dx, dy) = (mx - cx, my - cy);
        let distance = dx.hypot(dy);
        if distance < r * 0.37 {
            return STOP;
        }
        if distance > r || distance < r * 0.40 {
            return NONE;
        }
        let step = std::f32::consts::TAU / c.favorites().len() as f32;
        ((dy.atan2(dx) + std::f32::consts::FRAC_PI_2 + step / 2.).rem_euclid(std::f32::consts::TAU)
            / step)
            .floor() as i32
    }
    pub(super) fn cubeon_emote_wheel(&mut self, batch: &mut HudBatch) {
        let hit = self.wheel_hit();
        if self.companion.wheel_cursor != self.cursor {
            self.companion.wheel_focus = hit;
            self.companion.wheel_cursor = self.cursor;
        }
        let c = &mut self.companion;
        let (cx, cy, r, cw, rh) = layout(batch.width, batch.height);
        let favorites = c.favorites();
        let slots = favorites.len();
        let enabled = c.boolean("showEmotes", true);
        let selected = c.wheel_focus;
        let fade = if c.boolean("menuAnimations", true) {
            (c.opened.elapsed().as_secs_f32() / 0.14).min(1.)
        } else {
            1.
        };
        let mut ui = Canvas {
            batch,
            atlas: &self.gui.atlas,
            palette: c.palette,
            fade,
        };
        let (text, dim, faint, glass, hi, border, rim) = (
            0xfff5f5f5, 0xffc5c5c5, 0xff939393, 0x66343434, 0xa0787878, 0x608a8a8a, 0xb8cccccc,
        );
        if c.tab == 8 {
            let top = cy - rh * 2.5;
            ui.center("Edit emote favorites", cx, top - 27., text);
            ui.center(&format!("{slots} / 8"), cx, top - 13., dim);
            for i in 0..10 {
                let r = [
                    cx - cw + (i % 2) as f32 * cw + 3.,
                    top + (i / 2) as f32 * rh + 2.,
                    cw - 6.,
                    rh - 4.,
                ];
                let chosen = favorites.iter().any(|n| n == emotes::NAMES[i]);
                let hover = selected == i as i32;
                ui.panel(
                    r,
                    if hover { hi } else { glass },
                    if chosen || hover { rim } else { border },
                );
                emote_icon(
                    &mut ui,
                    i,
                    [r[0] + 6., r[1] + (r[3] - 20.) / 2., 20., 20.],
                    if chosen { text } else { dim },
                );
                let label = art::tr(&format!("emote.{}", emotes::NAMES[i]));
                ui.center(
                    &art::fit(ui.atlas, &label, r[2] - 36.),
                    r[0] + r[2] / 2. + 8.,
                    r[1] + (r[3] - 9.) / 2.,
                    if chosen { text } else { dim },
                );
                widgets::record(
                    &format!("{label} favorite: {}", if chosen { "On" } else { "Off" }),
                    r,
                    true,
                );
                widgets::target(r);
            }
            ui.center(
                if c.wheel_notice_at.elapsed().as_secs_f32() < 2. {
                    &c.wheel_notice
                } else {
                    "Choose up to eight favorites"
                },
                cx,
                top + rh * 5. + 6.,
                dim,
            );
            wheel_button(
                &mut ui,
                [cx - 65., top + rh * 5. + 20., 130., 20.],
                "Done",
                selected == DONE,
            );
            return;
        }
        for tile in 0..2 * slots + 2 {
            let color = if tile < slots {
                if selected == tile as i32 && enabled {
                    hi
                } else if tile % 2 == 0 {
                    glass
                } else {
                    0x70444444
                }
            } else if tile == slots {
                if selected == STOP {
                    0x80606060
                } else {
                    0x70252525
                }
            } else if tile == slots + 1 {
                border
            } else {
                if selected == (tile - slots - 2) as i32 && enabled {
                    rim
                } else {
                    border
                }
            };
            ui.image(
                &format!("cubeon/wheel/{slots}/{tile}"),
                [cx - r, cy - r, r * 2., r * 2.],
                [0., 0., 1., 1.],
                color,
            );
        }
        ui.center("Emotes", cx, cy - r - 22., text);
        let snapshot = c.bridge.snapshot_arc();
        ui.center(
            if snapshot.emotes["ready"].as_bool() == Some(true) {
                "Synced"
            } else {
                "Local preview · sync unavailable"
            },
            cx,
            cy + r + 15.,
            faint,
        );
        for (i, name) in favorites.iter().enumerate() {
            let angle =
                i as f32 * std::f32::consts::TAU / slots as f32 - std::f32::consts::FRAC_PI_2;
            let x = cx + (angle.cos() * r * 0.72).round();
            let y = cy + (angle.sin() * r * 0.72).round();
            let color = if !enabled {
                faint
            } else if selected == i as i32 {
                text
            } else {
                dim
            };
            let id = emotes::NAMES.iter().position(|n| *n == name).unwrap();
            let size = (r / 116. * 40.).round().max(14.);
            emote_icon(
                &mut ui,
                id,
                [x - size / 2., y - 7. - size / 2., size, size],
                color,
            );
            ui.center(&(i + 1).to_string(), x, y + 12., color);
            widgets::record(
                &format!("{} ({})", art::tr(&format!("emote.{name}")), i + 1),
                [x - 14., y - 20., 28., 40.],
                enabled,
            );
            widgets::target([x - 14., y - 20., 28., 40.]);
        }
        let label = if selected >= 0 {
            art::tr(&format!(
                "emote.{}",
                favorites
                    .get(selected as usize)
                    .map(String::as_str)
                    .unwrap_or("wave")
            ))
        } else {
            "Stop".into()
        };
        ui.center(
            &art::fit(ui.atlas, &label, r * 0.74 - 6.),
            cx,
            cy - 3.,
            text,
        );
        widgets::record("Stop emote", [cx - 12., cy - 6., 24., 12.], true);
        let width = center_width(r);
        wheel_button(
            &mut ui,
            [cx - width / 2., cy - 20., width, 12.],
            if enabled { "ON" } else { "OFF" },
            selected == TOGGLE,
        );
        wheel_button(
            &mut ui,
            [cx - width / 2., cy + 8., width, 12.],
            "Edit",
            selected == EDIT,
        );
    }
    pub(super) fn cubeon_emote_key(&mut self, key: KeyCode, pressed: bool, repeat: bool) -> bool {
        if !pressed {
            if key == KeyCode::KeyB && self.companion.tab == 5 && self.companion.wheel_held {
                self.companion.wheel_held = false;
                let hit = self.wheel_hit();
                if hit >= 0 {
                    self.companion.wheel_focus = hit;
                    self.cubeon_emote_choose();
                } else {
                    self.cubeon_back();
                }
            }
            return true;
        }
        if repeat {
            return true;
        }
        if key == KeyCode::Escape {
            self.cubeon_back();
            return true;
        }
        if key == KeyCode::KeyE {
            if self.companion.tab == 8 {
                self.companion.tab = 5;
            } else {
                self.companion.tab = 8;
            }
            self.companion.wheel_held = false;
            self.companion.wheel_focus = NONE;
            return true;
        }
        let number = match key {
            KeyCode::Digit1 => Some(0),
            KeyCode::Digit2 => Some(1),
            KeyCode::Digit3 => Some(2),
            KeyCode::Digit4 => Some(3),
            KeyCode::Digit5 => Some(4),
            KeyCode::Digit6 => Some(5),
            KeyCode::Digit7 => Some(6),
            KeyCode::Digit8 => Some(7),
            _ => None,
        };
        if let Some(i) = number {
            if self.companion.tab == 5 && i < self.companion.favorites().len() {
                self.companion.wheel_focus = i as i32;
                self.cubeon_emote_choose();
            }
            return true;
        }
        if matches!(
            key,
            KeyCode::ArrowLeft
                | KeyCode::ArrowRight
                | KeyCode::ArrowUp
                | KeyCode::ArrowDown
                | KeyCode::Tab
        ) {
            let choices = if self.companion.tab == 8 {
                10
            } else {
                self.companion.favorites().len() as i32
            };
            let d = if matches!(key, KeyCode::ArrowLeft | KeyCode::ArrowUp) {
                -1
            } else {
                1
            };
            let c = &mut self.companion;
            c.wheel_focus = if c.wheel_focus < 0 {
                0
            } else {
                (c.wheel_focus + d).rem_euclid(choices)
            };
            c.wheel_cursor = self.cursor;
            return true;
        }
        if matches!(key, KeyCode::Enter | KeyCode::Space) {
            self.cubeon_emote_choose();
        }
        true
    }
    pub(super) fn cubeon_emote_click(&mut self, right: bool) {
        if right {
            self.cubeon_back();
            return;
        }
        self.companion.wheel_focus = self.wheel_hit();
        self.cubeon_emote_choose();
    }
    pub(super) fn cubeon_emote_choose(&mut self) {
        let selected = self.companion.wheel_focus;
        if self.companion.tab == 8 {
            if selected == DONE {
                self.companion.tab = 5;
                return;
            }
            if !(0..10).contains(&selected) {
                return;
            }
            let name = emotes::NAMES[selected as usize];
            let mut favorites = self.companion.favorites();
            if let Some(i) = favorites.iter().position(|n| n == name) {
                if favorites.len() == 1 {
                    self.companion.wheel_notice = "Keep at least one favorite".into();
                    self.companion.wheel_notice_at = std::time::Instant::now();
                    return;
                }
                favorites.remove(i);
            } else {
                if favorites.len() == 8 {
                    self.companion.wheel_notice = "Eight favorites selected".into();
                    self.companion.wheel_notice_at = std::time::Instant::now();
                    return;
                }
                favorites.push(name.into());
            }
            self.companion.config["emoteFavorites"] = json!(favorites);
            self.companion.save();
            return;
        }
        if selected == TOGGLE {
            let on = !self.companion.boolean("showEmotes", true);
            if !on {
                self.cubeon_play_emote("stop");
            }
            self.companion.config["showEmotes"] = json!(on);
            self.companion.save();
        } else if selected == EDIT {
            self.companion.tab = 8;
            self.companion.wheel_held = false;
            self.companion.wheel_focus = NONE;
        } else if selected == STOP {
            self.cubeon_play_emote("stop");
            self.cubeon_back();
        } else if selected >= 0 && self.companion.boolean("showEmotes", true) {
            if let Some(name) = self.companion.favorites().get(selected as usize) {
                self.cubeon_play_emote(name);
            }
            self.cubeon_back();
        }
    }
}
fn emote_icon(ui: &mut Canvas<'_>, id: usize, r: [f32; 4], color: u32) {
    ui.image(
        "cubeon/ui/emotes",
        r,
        [id as f32 / 11., 0., (id + 1) as f32 / 11., 1.],
        color,
    );
}
fn wheel_button(ui: &mut Canvas<'_>, r: [f32; 4], label: &str, hover: bool) {
    ui.panel(
        r,
        if hover { 0xa0787878 } else { 0x66343434 },
        if hover { 0xb8cccccc } else { 0x608a8a8a },
    );
    ui.center(
        &art::fit(ui.atlas, label, r[2] - 8.),
        r[0] + r[2] / 2.,
        r[1] + (r[3] - 9.) / 2.,
        0xffc5c5c5,
    );
    widgets::record(label, r, true);
    widgets::target(r);
}
