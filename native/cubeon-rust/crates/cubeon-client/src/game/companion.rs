//! Cubeon Client's native HUD, settings, social screens and camera-only controls.
use super::{Game, Screen, perspective::CameraType};
use cubeon_client::{
    cubeon_bridge::Bridge,
    hud::{HudAtlas, HudBatch, rgba},
    text::Text,
    ui,
};
use serde_json::{Value, json};
use std::time::Instant;
use winit::keyboard::KeyCode;

pub(super) const FEATURES: [(&str, &str, f32, f32); 13] = [
    ("fps", "FPS", 64., 12.),
    ("keys", "Keystrokes", 66., 76.),
    ("armor", "Armor", 96., 28.),
    ("ping", "Ping", 64., 12.),
    ("cps", "CPS", 64., 12.),
    ("clock", "Clock", 84., 12.),
    ("system", "System", 146., 24.),
    ("potions", "Potions", 150., 74.),
    ("coordinates", "Coordinates", 146., 24.),
    ("direction", "Direction", 112., 12.),
    ("biome", "Biome", 132., 12.),
    ("daylight", "Daylight", 146., 24.),
    ("combo", "Combo", 72., 12.),
];
const TOGGLES: [(&str, &str, bool); 7] = [
    ("showEnemyHealth", "Enemy health", false),
    ("autoSprint", "Auto sprint", false),
    ("showEmotes", "Player emotes", true),
    ("showArmorHelmet", "Helmet", true),
    ("showArmorChest", "Chestplate", true),
    ("showArmorLegs", "Leggings", true),
    ("showArmorFeet", "Boots", true),
];

pub(super) struct Companion {
    pub enabled: bool,
    pub open: bool,
    pub frame_ms: f32,
    pub clicks: [std::collections::VecDeque<Instant>; 2],
    pub config: Value,
    pub bridge: Bridge,
    pub tab: usize,
    page: usize,
    text: String,
    peer: String,
    friend_name: String,
    buttons: Vec<(usize, [f32; 4], String)>,
    pub free: Option<(CameraType, f32, f32)>,
    blocked: bool,
    pub distance: f32,
    target_distance: f32,
    pub selected: Option<usize>,
    drag: Option<(f32, f32)>,
    pub wing_started: Option<Instant>,
    pub combo: u32,
    pub combo_at: Instant,
    pub combo_target: Option<u32>,
    pub emote_serial: i64,
}
impl Companion {
    pub fn new(root: std::path::PathBuf) -> Self {
        let config = std::fs::read(root.join("config/cubeon-client-hud.json"))
            .ok()
            .filter(|b| b.len() <= 65536)
            .and_then(|b| serde_json::from_slice(&b).ok())
            .filter(|v: &Value| v.is_object())
            .unwrap_or_else(|| json!({}));
        Self {
            enabled: std::env::var("CUBEON_CLIENT_ENABLED").as_deref() != Ok("0"),
            open: false,
            frame_ms: 16.7,
            clicks: Default::default(),
            config,
            bridge: Bridge::new(),
            tab: 0,
            page: 0,
            text: String::new(),
            peer: String::new(),
            friend_name: String::new(),
            buttons: Vec::new(),
            free: None,
            blocked: false,
            distance: 4.,
            target_distance: 4.,
            selected: None,
            drag: None,
            wing_started: None,
            combo: 0,
            combo_at: Instant::now(),
            combo_target: None,
            emote_serial: 0,
        }
    }
    pub fn boolean(&self, key: &str, default: bool) -> bool {
        self.config[key].as_bool().unwrap_or(default)
    }
    pub fn number(&self, key: &str, default: f32, min: f32, max: f32) -> f32 {
        self.config[key]
            .as_f64()
            .filter(|v| v.is_finite())
            .map(|v| v as f32)
            .unwrap_or(default)
            .clamp(min, max)
    }
    pub fn enabled(&self, i: usize) -> bool {
        if i < 5 {
            self.boolean(
                ["showFps", "showKeys", "showArmor", "showPing", "showCps"][i],
                false,
            )
        } else {
            self.config["extraOverlays"][FEATURES[i].0]["enabled"]
                .as_bool()
                .unwrap_or(false)
        }
    }
    pub fn position(&self, i: usize) -> (f32, f32, f32) {
        let defaults = [
            (0., 0.),
            (0., 0.55),
            (1., 0.35),
            (1., 0.),
            (0., 0.1),
            (0.5, 0.),
            (1., 0.42),
            (1., 0.62),
            (0., 0.2),
            (0.5, 0.08),
            (0., 0.32),
            (0., 0.42),
            (0.5, 0.72),
        ];
        let slot = FEATURES[i].0;
        let (x, y) = defaults[i];
        let read = |v: &Value, d: f32, min: f32, max: f32| {
            v.as_f64()
                .filter(|v| v.is_finite())
                .map(|v| v as f32)
                .unwrap_or(d)
                .clamp(min, max)
        };
        let s = self.number("scale", 1., 0.5, 2.);
        if i < 5 {
            (
                self.number(&format!("{slot}X"), x, 0., 1.),
                self.number(&format!("{slot}Y"), y, 0., 1.),
                self.number(&format!("{slot}Scale"), s, 0.5, 2.),
            )
        } else {
            let v = &self.config["extraOverlays"][slot];
            (
                read(&v["x"], x, 0., 1.),
                read(&v["y"], y, 0., 1.),
                read(&v["scale"], s, 0.5, 2.),
            )
        }
    }
    fn toggle(&mut self, i: usize) {
        let enabled = !self.enabled(i);
        if i < 5 {
            self.config[["showFps", "showKeys", "showArmor", "showPing", "showCps"][i]] =
                json!(enabled);
        } else {
            self.config["extraOverlays"][FEATURES[i].0]["enabled"] = json!(enabled);
        }
    }
    pub fn save(&self) {
        let path = Game::game_dir().join("config/cubeon-client-hud.json");
        let temp = path.with_extension("json.tmp");
        if let Some(parent) = path.parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        if let Ok(bytes) = serde_json::to_vec_pretty(&self.config)
            && std::fs::write(&temp, bytes).is_ok()
        {
            if let Err(e) = std::fs::rename(&temp, &path) {
                log::warn!("Cubeon settings could not be saved: {e}");
            }
        }
    }
    pub fn scroll(&mut self, d: f32, screen: Screen) -> bool {
        if screen == Screen::Friends {
            if self.tab == 4
                && let Some(i) = self.selected
            {
                let s = (self.position(i).2 + d.signum() * 0.1).clamp(0.5, 2.);
                if i < 5 {
                    self.config[format!("{}Scale", FEATURES[i].0)] = json!(s);
                } else {
                    self.config["extraOverlays"][FEATURES[i].0]["scale"] = json!(s);
                }
                self.save();
            } else if d > 0. {
                self.page = self.page.saturating_sub(1);
            } else if d < 0. {
                self.page += 1;
            }
            return true;
        }
        if self.free.is_some() && d != 0. {
            self.target_distance = (self.target_distance * 1.2f32.powf(-d)).clamp(1., 12.);
            return true;
        }
        false
    }
}
fn button(batch: &mut HudBatch, atlas: &HudAtlas, cursor: (f32, f32), rect: [f32; 4], label: &str) {
    ui::button(
        batch,
        atlas,
        rect[0],
        rect[1],
        rect[2],
        rect[3],
        &Text::literal(label),
        true,
        ui::hovered(cursor, rect[0], rect[1], rect[2], rect[3]),
    );
}
impl Game<'_> {
    pub(super) fn cubeon_hit(&mut self, target: u32) {
        if self.companion.combo_target == Some(target)
            && self.companion.combo_at.elapsed().as_secs_f32() < 3.
        {
            self.companion.combo = self.companion.combo.saturating_add(1);
        } else {
            self.companion.combo = 1;
        }
        self.companion.combo_target = Some(target);
        self.companion.combo_at = Instant::now();
    }
    pub(super) fn cubeon_frame(&mut self, elapsed: std::time::Duration) {
        if !self.companion.enabled {
            return;
        }
        self.companion.frame_ms += (elapsed.as_secs_f32() * 1000. - self.companion.frame_ms) * 0.1;
        for clicks in &mut self.companion.clicks {
            while clicks
                .front()
                .is_some_and(|at| at.elapsed().as_secs_f32() > 1.)
            {
                clicks.pop_front();
            }
        }
        if self.screen != Screen::Friends {
            self.companion.open = false;
        }
        let eligible = self.screen == Screen::Playing
            && !self.remote_loading()
            && self.title.is_none()
            && (self.focused || self.control.is_some())
            && !self.screen_over_playing()
            && self.player.is_some();
        let held = self.physical_keys.contains(&KeyCode::AltLeft);
        if !held {
            self.companion.blocked = false;
        }
        if let Some((previous, _, _)) = self.companion.free
            && (!held || !eligible || self.camera_type != CameraType::ThirdPersonBack)
        {
            self.companion.free = None;
            self.companion.blocked = held;
            if self.camera_type == CameraType::ThirdPersonBack {
                self.camera_type = previous;
            }
        }
        if !eligible && held {
            self.companion.blocked = true;
        }
        if self.companion.free.is_none() && held && eligible && !self.companion.blocked {
            let front = self.camera_type == CameraType::ThirdPersonFront;
            self.companion.free = Some((
                self.camera_type,
                self.yaw + if front { 180. } else { 0. },
                if front { -self.pitch } else { self.pitch },
            ));
            self.camera_type = CameraType::ThirdPersonBack;
        }
        self.companion.distance += (self.companion.target_distance - self.companion.distance)
            * (1. - (-elapsed.as_secs_f32() / 0.1).exp());
        let address = if self.player.is_some() && self.companion.boolean("showEmotes", true) {
            self.server_address()
                .map(str::to_owned)
                .unwrap_or_else(|| format!("single:{}", self.options.player_name()))
        } else {
            String::new()
        };
        self.companion.bridge.context(if address.is_empty() {
            address
        } else {
            use sha2::{Digest, Sha256};
            let address = address.to_ascii_lowercase();
            let address = address.strip_suffix(":25565").unwrap_or(&address);
            format!(
                "{:x}",
                Sha256::digest(format!("cubeon-emotes-v1:{address}").as_bytes())
            )
        });
        let snapshot = self.companion.bridge.snapshot().clone();
        self.cubeon_emotes_frame(&snapshot.emotes, eligible);
        if self.companion.combo_at.elapsed().as_secs_f32() > 3. {
            self.companion.combo = 0;
        }
        if self.companion.boolean("autoSprint", false)
            && eligible
            && self.keys.contains(&KeyCode::KeyW)
            && !self.keys.contains(&KeyCode::ShiftLeft)
            && let Some(p) = self.player.as_mut()
            && p.health.food.food > 6
        {
            p.sprinting = true;
        }
        if self.screen != Screen::Friends || !self.companion.open || self.companion.tab != 3 {
            self.companion.bridge.chat(String::new());
        }
    }
    pub(super) fn cubeon_key(&mut self, key: KeyCode, pressed: bool, repeat: bool) -> bool {
        if !self.companion.enabled || (!self.companion.open && self.remote_loading()) {
            return false;
        }
        if key == KeyCode::ShiftRight
            && pressed
            && !repeat
            && matches!(self.screen, Screen::Playing | Screen::Paused)
            && self.title.is_none()
            && !self.screen_over_playing()
        {
            self.companion.open = true;
            self.screen = Screen::Friends;
            self.companion.tab = 0;
            self.companion.page = 0;
            return true;
        }
        if key == KeyCode::KeyB
            && self.title.is_none()
            && self.companion.boolean("showEmotes", true)
        {
            if pressed && !repeat && self.screen == Screen::Playing && !self.screen_over_playing() {
                self.companion.open = true;
                self.companion.tab = 5;
                self.screen = Screen::Friends;
                return true;
            }
            if !pressed
                && self.companion.open
                && self.screen == Screen::Friends
                && self.companion.tab == 5
            {
                self.cubeon_emote_choose();
                return true;
            }
        }
        if key == KeyCode::KeyN && pressed && !repeat && self.screen == Screen::Playing {
            if self
                .companion
                .wing_started
                .is_none_or(|t| t.elapsed().as_secs_f32() >= 3.25)
            {
                self.companion.wing_started = Some(Instant::now());
            }
        }
        if self.screen != Screen::Friends || !self.companion.open {
            return false;
        }
        if pressed {
            match key {
                KeyCode::Escape => {
                    self.companion.bridge.chat(String::new());
                    self.companion.drag = None;
                    self.screen = if self.companion.tab >= 4 {
                        Screen::Playing
                    } else {
                        Screen::Paused
                    };
                    self.companion.save();
                }
                KeyCode::Backspace => {
                    self.companion.text.pop();
                }
                KeyCode::Enter => self.cubeon_input_send(),
                KeyCode::ArrowLeft => self.companion.page = self.companion.page.saturating_sub(1),
                KeyCode::ArrowRight => self.companion.page += 1,
                _ => {}
            }
        }
        true
    }
    pub(super) fn cubeon_chars(&mut self, text: &str) {
        if self.screen == Screen::Friends
            && self.companion.open
            && matches!(self.companion.tab, 2 | 3)
        {
            for c in text.chars().filter(|c| !c.is_control()) {
                if self.companion.text.chars().count()
                    >= if self.companion.tab == 2 { 32 } else { 1000 }
                {
                    break;
                }
                self.companion.text.push(c);
            }
        }
    }
    fn cubeon_input_send(&mut self) {
        let c = &mut self.companion;
        if c.text.trim().is_empty() {
            return;
        }
        let accepted = if c.tab == 2 {
            c.bridge.action("/add", json!({"name":c.text.trim()}))
        } else if c.tab == 3 {
            c.bridge
                .action("/dm", json!({"to":c.peer,"text":c.text.trim()}))
        } else {
            false
        };
        if accepted {
            c.text.clear();
        }
    }
    pub(super) fn cubeon_screen(&mut self, batch: &mut HudBatch) {
        cubeon_client::widgets::begin_screen(|| {
            cubeon_client::widgets::ScreenInfo::new("cubeon_client", "Cubeon Client")
        });
        if self.companion.tab == 5 {
            self.cubeon_emote_wheel(batch);
            return;
        }
        if self.companion.tab == 4 {
            self.cubeon_hud(batch, true);
        } else {
            ui::menu_background(
                batch,
                &self.gui.atlas,
                0.,
                0.,
                batch.width,
                batch.height,
                self.player.is_some(),
            );
        }
        let (w, h) = (batch.width, batch.height);
        let bw = (w - 32.).min(380.);
        let x = (w - bw) / 2.;
        let atlas = &self.gui.atlas;
        batch.text(
            atlas,
            "Cubeon Client · Rust Edition",
            x,
            14.,
            u32::MAX,
            true,
        );
        let mut buttons = Vec::new();
        let mut add = |id, rect, label: String| {
            buttons.push((id, rect, label));
        };
        for (i, label) in ["HUD", "Settings", "Friends"].iter().enumerate() {
            add(
                i,
                [x + i as f32 * bw / 3., 34., bw / 3. - 3., 20.],
                (*label).into(),
            );
        }
        let rows = ((h - 148.) / 23.).floor().max(1.) as usize;
        if self.companion.tab <= 1 {
            let count = if self.companion.tab == 0 {
                FEATURES.len()
            } else {
                TOGGLES.len()
            };
            self.companion.page = self.companion.page.min((count - 1) / rows);
            for i in self.companion.page * rows..count.min((self.companion.page + 1) * rows) {
                let label = if self.companion.tab == 0 {
                    format!(
                        "{}: {}",
                        FEATURES[i].1,
                        if self.companion.enabled(i) {
                            "On"
                        } else {
                            "Off"
                        }
                    )
                } else {
                    format!(
                        "{}: {}",
                        TOGGLES[i].1,
                        if self.companion.boolean(TOGGLES[i].0, TOGGLES[i].2) {
                            "On"
                        } else {
                            "Off"
                        }
                    )
                };
                add(
                    100 + i,
                    [
                        x,
                        64. + (i - self.companion.page * rows) as f32 * 23.,
                        bw,
                        20.,
                    ],
                    label,
                );
            }
        } else if matches!(self.companion.tab, 2 | 3) {
            let snapshot = self.companion.bridge.snapshot().clone();
            let label = if self.companion.tab == 2 {
                if snapshot.up {
                    "Connected to Cubeon"
                } else {
                    "Looking for Cubeon launcher"
                }
            } else {
                &self.companion.friend_name
            };
            batch.text(atlas, label, x, 60., rgba(170, 207, 196, 255), false);
            if self.companion.tab == 2 {
                let friends = snapshot.friends["friends"]
                    .as_array()
                    .cloned()
                    .unwrap_or_default();
                self.companion.page = self
                    .companion
                    .page
                    .min(friends.len().saturating_sub(1) / rows);
                for i in
                    self.companion.page * rows..friends.len().min((self.companion.page + 1) * rows)
                {
                    let friend = &friends[i];
                    let label = friend["minecraft_username"]
                        .as_str()
                        .filter(|n| !n.is_empty())
                        .unwrap_or("Player");
                    let uid = friend["uid"].as_str().unwrap_or("");
                    add(
                        300 + i,
                        [
                            x,
                            76. + (i - self.companion.page * rows) as f32 * 23.,
                            bw,
                            20.,
                        ],
                        format!(
                            "{label} · {uid} · {}",
                            if friend["online"].as_bool() == Some(true) {
                                "Online"
                            } else {
                                "Offline"
                            }
                        ),
                    );
                }
            } else {
                let messages = snapshot.chat["messages"]
                    .as_array()
                    .cloned()
                    .unwrap_or_default();
                let mut lines = Vec::new();
                for message in messages {
                    let from = if message["direction"].as_str() == Some("out") {
                        "You"
                    } else {
                        &self.companion.friend_name
                    };
                    lines.extend(cubeon_client::multiplayer::wrap(
                        &format!("{from}: {}", message["text"].as_str().unwrap_or("")),
                        bw,
                        atlas,
                    ));
                }
                let visible = ((h - 170.) / 10.).floor().max(1.) as usize;
                for (i, line) in lines
                    .iter()
                    .skip(lines.len().saturating_sub(visible))
                    .enumerate()
                {
                    batch.text(atlas, line, x, 75. + i as f32 * 10., u32::MAX, false);
                }
            }
            batch.fill(atlas, x, h - 89., bw - 65., 20., rgba(31, 49, 54, 230));
            batch.text(
                atlas,
                &self.companion.text,
                x + 3.,
                h - 83.,
                u32::MAX,
                false,
            );
            add(
                20,
                [x + bw - 62., h - 89., 62., 20.],
                if self.companion.tab == 2 {
                    "Add ID"
                } else {
                    "Send"
                }
                .into(),
            );
            if !snapshot.error.is_empty() {
                batch.text(
                    atlas,
                    &snapshot.error,
                    x,
                    h - 103.,
                    rgba(255, 180, 155, 255),
                    false,
                );
            }
        }
        add(10, [x, h - 64., bw / 4. - 3., 20.], "Previous".into());
        add(11, [x + bw / 4., h - 64., bw / 4. - 3., 20.], "Next".into());
        add(12, [x + bw / 2., h - 64., bw / 2., 20.], "Edit HUD".into());
        add(
            13,
            [x, h - 40., bw / 2. - 3., 20.],
            format!(
                "Zoom: {:.1}×",
                self.companion.number("zoomFactor", 4., 1.25, 8.)
            ),
        );
        add(14, [x + bw / 2., h - 40., bw / 2., 20.], "Done".into());
        for (_, rect, label) in &buttons {
            button(batch, atlas, self.cursor, *rect, label);
        }
        self.companion.buttons = buttons;
    }
    pub(super) fn cubeon_click(&mut self, right: bool) {
        if self.companion.tab == 5 {
            self.cubeon_emote_choose();
            return;
        }
        if self.companion.tab == 4 {
            for i in (0..FEATURES.len()).rev() {
                let (x, y, s) = self.companion.position(i);
                let (w, h) = self.gui_size();
                let f = FEATURES[i];
                let px = x * (w - f.2 * s).max(0.);
                let py = y * (h - f.3 * s).max(0.);
                if ui::hovered(self.cursor, px, py, f.2 * s, f.3 * s) {
                    self.companion.selected = Some(i);
                    if right {
                        self.companion.toggle(i);
                    } else {
                        self.companion.drag = Some((self.cursor.0 - px, self.cursor.1 - py));
                    }
                    self.companion.save();
                    break;
                }
            }
        }
        let id = self
            .companion
            .buttons
            .iter()
            .find(|(_, r, _)| ui::hovered(self.cursor, r[0], r[1], r[2], r[3]))
            .map(|b| b.0);
        if let Some(id) = id {
            match id {
                0..=2 => {
                    self.companion.tab = id;
                    self.companion.page = 0;
                    self.companion.text.clear();
                }
                10 => self.companion.page = self.companion.page.saturating_sub(1),
                11 => self.companion.page += 1,
                12 => self.companion.tab = 4,
                13 => {
                    let z = self.companion.number("zoomFactor", 4., 1.25, 8.);
                    self.companion.config["zoomFactor"] =
                        json!(if z >= 8. { 1.5 } else { z + 0.5 });
                }
                14 => {
                    self.companion.bridge.chat(String::new());
                    self.screen = Screen::Playing;
                }
                20 => self.cubeon_input_send(),
                100..=112 => {
                    let i = id - 100;
                    if self.companion.tab == 0 {
                        self.companion.toggle(i);
                    } else if i < TOGGLES.len() {
                        let key = TOGGLES[i].0;
                        let on = !self.companion.boolean(key, TOGGLES[i].2);
                        self.companion.config[key] = json!(on);
                    }
                }
                300.. => {
                    let i = id - 300;
                    let snapshot = self.companion.bridge.snapshot().clone();
                    if let Some(friend) = snapshot.friends["friends"].get(i) {
                        self.companion.peer = friend["name"].as_str().unwrap_or("").into();
                        self.companion.friend_name = friend["minecraft_username"]
                            .as_str()
                            .unwrap_or("Player")
                            .into();
                        self.companion.bridge.chat(self.companion.peer.clone());
                        self.companion.tab = 3;
                        self.companion.text.clear();
                    }
                }
                _ => {}
            }
            self.companion.save();
        }
    }
    pub(super) fn cubeon_drag(&mut self, held: bool) {
        if !held {
            if self.companion.drag.take().is_some() {
                self.companion.save();
            }
            return;
        }
        if self.screen == Screen::Friends
            && self.companion.tab == 4
            && let Some(i) = self.companion.selected
            && let Some((dx, dy)) = self.companion.drag
        {
            let (w, h) = self.gui_size();
            let f = FEATURES[i];
            let s = self.companion.position(i).2;
            let x = ((self.cursor.0 - dx) / (w - f.2 * s).max(1.)).clamp(0., 1.);
            let y = ((self.cursor.1 - dy) / (h - f.3 * s).max(1.)).clamp(0., 1.);
            if i < 5 {
                self.companion.config[format!("{}X", f.0)] = json!(x);
                self.companion.config[format!("{}Y", f.0)] = json!(y);
            } else {
                self.companion.config["extraOverlays"][f.0]["x"] = json!(x);
                self.companion.config["extraOverlays"][f.0]["y"] = json!(y);
            }
        }
    }
}
