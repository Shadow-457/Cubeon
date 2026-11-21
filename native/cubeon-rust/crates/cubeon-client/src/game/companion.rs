//! Native Cubeon Client state, shared settings and input. Drawing lives in the
//! companion menu/social/wheel modules; launcher I/O stays on Bridge's worker.
use super::{Game, Screen, perspective::CameraType};
use cubeon_client::{cubeon_bridge::Bridge, hud::HudBatch, ui::EditBox};
use cubeon_client_render::cubeon_ui::{self as art, PRESETS, Palette};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, VecDeque},
    time::Instant,
};
use winit::keyboard::KeyCode;

pub(super) const FEATURES: [(&str, &str, f32, f32); 13] = [
    ("fps", "HUD", 64., 12.),
    ("keys", "HUD", 66., 76.),
    ("armor", "Player", 96., 28.),
    ("ping", "HUD", 64., 12.),
    ("cps", "HUD", 64., 12.),
    ("clock", "HUD", 84., 12.),
    ("system", "HUD", 146., 24.),
    ("potions", "Player", 150., 74.),
    ("coordinates", "HUD", 146., 24.),
    ("direction", "HUD", 112., 12.),
    ("biome", "HUD", 132., 12.),
    ("daylight", "HUD", 146., 24.),
    ("combo", "Player", 72., 12.),
];
pub(super) const EXTRAS: [(&str, &str, &str, bool); 6] = [
    ("sprint", "Movement", "autoSprint", false),
    ("camera_blur", "Render", "cameraMotionBlur", false),
    ("full_bright", "Render", "fullBright", false),
    ("health", "Player", "showEnemyHealth", false),
    ("menu_animations", "Render", "menuAnimations", true),
    ("own_name_tag", "Player", "showOwnNameTag", false),
];
#[derive(Clone, Copy, Debug, PartialEq)]
pub(super) enum Action {
    Toggle(usize),
    Detail(usize),
    Category(usize),
    Page(i32),
    Open(usize),
    Back,
    Close,
    Reset,
    Field(usize),
    Scale(usize),
    Setting(&'static str, bool),
    Theme(usize),
    Role(usize),
    ApplyTheme,
    Friend(usize),
    FriendsMode(bool),
    Add,
    Send,
    Request(usize, bool),
    CancelRequest(usize),
    Remove,
    ConfirmRemove,
    FriendPage(i32),
    CopyId,
}
#[derive(Clone)]
pub(super) struct Control {
    pub action: Action,
    pub rect: [f32; 4],
    pub label: String,
    pub enabled: bool,
}
pub(super) struct PendingSend {
    pub id: u64,
    pub account: String,
    pub peer: String,
    pub text: String,
    pub generation: u64,
}
pub(super) struct Bubble {
    pub out: bool,
    pub lines: Vec<String>,
    pub width: f32,
    pub height: f32,
    pub y: f32,
}
#[derive(Default)]
pub(super) struct Transcript {
    pub key: Option<(u64, String, i64, usize, u32, u32)>,
    pub bubbles: Vec<Bubble>,
}
pub(super) struct Notice {
    pub text: String,
    pub error: bool,
    pub born: Instant,
}
pub(super) struct Companion {
    pub enabled: bool,
    pub open: bool,
    pub frame_ms: f32,
    pub clicks: [VecDeque<Instant>; 2],
    pub config: Value,
    pub bridge: Bridge,
    pub tab: usize,
    pub page: usize,
    pub pages: usize,
    pub category: usize,
    pub detail: usize,
    pub controls: Vec<Control>,
    pub focus: Option<usize>,
    pub field: Option<usize>,
    pub search: EditBox,
    pub composer: EditBox,
    pub add: EditBox,
    pub hex: EditBox,
    pub peer: String,
    pub account: String,
    pub generation: u64,
    pub drafts: HashMap<(String, String), String>,
    pub pending: Option<PendingSend>,
    pub local_error: String,
    pub social_pending: Option<(u64, String, String, u64)>,
    pub remove_confirm: bool,
    pub friend_rail: [f32; 4],
    pub transcript: Transcript,
    pub friend_offset: usize,
    pub transcript_scroll: f32,
    pub transcript_height: f32,
    pub manage_friends: bool,
    pub notices: VecDeque<Notice>,
    pub event_seen: i64,
    pub theme: usize,
    pub palette: Palette,
    pub custom_palette: Palette,
    pub theme_draft: usize,
    pub theme_custom: Palette,
    pub role: usize,
    pub wheel_focus: i32,
    pub wheel_cursor: (f32, f32),
    pub wheel_held: bool,
    pub wheel_notice: String,
    pub wheel_notice_at: Instant,
    pub free: Option<(CameraType, f32, f32)>,
    blocked: bool,
    pub distance: f32,
    target_distance: f32,
    pub selected: Option<usize>,
    pub bounds: [[f32; 4]; 13],
    pub drag: Option<(f32, f32)>,
    pub slider: Option<(usize, [f32; 4])>,
    pub combo: u32,
    pub combo_at: Instant,
    pub combo_target: Option<u32>,
    pub emote_serial: i64,
    pub parents: Vec<usize>,
    pub return_screen: Screen,
    pub opened: Instant,
    pub pointer_select: bool,
    pub camera_blur: cubeon_client_render::cubeon_blur::CameraBlur,
    pub blur_clock: Instant,
}
fn field(max: usize, message: &str) -> EditBox {
    let mut field = EditBox::new(0., 0., 0., 9.);
    field.bordered = false;
    field.focused = false;
    field.max_length = max;
    field.message = message.into();
    field
}
impl Companion {
    pub fn new(root: std::path::PathBuf) -> Self {
        let config = std::fs::read(root.join("config/cubeon-client-hud.json"))
            .ok()
            .filter(|b| b.len() <= 65536)
            .and_then(|b| serde_json::from_slice(&b).ok())
            .filter(|v: &Value| v.is_object())
            .unwrap_or_else(|| json!({}));
        let (theme, custom_palette) = Palette::load(&root);
        let palette = if theme < 5 {
            Palette(PRESETS[theme])
        } else {
            custom_palette
        };
        Self {
            enabled: std::env::var("CUBEON_CLIENT_ENABLED").as_deref() != Ok("0"),
            open: false,
            frame_ms: 16.7,
            clicks: Default::default(),
            config,
            bridge: Bridge::new(),
            tab: 0,
            page: 0,
            pages: 1,
            category: 0,
            detail: 0,
            controls: Vec::new(),
            focus: None,
            field: None,
            search: field(40, "Search features"),
            composer: field(1000, "Message"),
            add: field(32, "Cubeon ID"),
            hex: field(6, "Hex color"),
            peer: String::new(),
            account: String::new(),
            generation: 0,
            drafts: HashMap::new(),
            pending: None,
            local_error: String::new(),
            transcript: Transcript::default(),
            social_pending: None,
            remove_confirm: false,
            friend_rail: [0.; 4],
            friend_offset: 0,
            transcript_scroll: 0.,
            transcript_height: 0.,
            manage_friends: false,
            notices: VecDeque::new(),
            event_seen: -1,
            theme,
            palette,
            custom_palette,
            theme_draft: theme,
            theme_custom: custom_palette,
            role: 0,
            wheel_focus: -2,
            wheel_cursor: (f32::NAN, f32::NAN),
            wheel_held: false,
            wheel_notice: String::new(),
            wheel_notice_at: Instant::now(),
            free: None,
            blocked: false,
            distance: 4.,
            target_distance: 4.,
            selected: None,
            bounds: [[0.; 4]; 13],
            drag: None,
            slider: None,
            combo: 0,
            combo_at: Instant::now(),
            combo_target: None,
            emote_serial: 0,
            parents: Vec::new(),
            return_screen: Screen::Playing,
            opened: Instant::now(),
            pointer_select: false,
            camera_blur: Default::default(),
            blur_clock: Instant::now(),
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
    pub fn feature_enabled(&self, i: usize) -> bool {
        if i < 13 {
            self.enabled(i)
        } else {
            let f = EXTRAS[i - 13];
            self.boolean(f.2, f.3)
        }
    }
    pub fn feature(i: usize) -> (&'static str, &'static str) {
        if i < 13 {
            (FEATURES[i].0, FEATURES[i].1)
        } else {
            (EXTRAS[i - 13].0, EXTRAS[i - 13].1)
        }
    }
    pub fn toggle(&mut self, i: usize) {
        let on = !self.feature_enabled(i);
        if i < 5 {
            self.config[["showFps", "showKeys", "showArmor", "showPing", "showCps"][i]] = json!(on);
        } else if i < 13 {
            self.config["extraOverlays"][FEATURES[i].0]["enabled"] = json!(on);
        } else {
            self.config[EXTRAS[i - 13].2] = json!(on);
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
        let (x, y) = defaults[i];
        let slot = FEATURES[i].0;
        let s = self.number("scale", 1., 0.5, 2.);
        let read = |v: &Value, d: f32, min: f32, max: f32| {
            v.as_f64()
                .filter(|v| v.is_finite())
                .map(|v| v as f32)
                .unwrap_or(d)
                .clamp(min, max)
        };
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
    pub fn set_scale(&mut self, i: usize, value: f32) {
        if i < 5 {
            self.config[format!("{}Scale", FEATURES[i].0)] = json!(value.clamp(0.5, 2.));
        } else if i < 13 {
            self.config["extraOverlays"][FEATURES[i].0]["scale"] = json!(value.clamp(0.5, 2.));
        } else if i == 13 {
            self.config["cameraBlurIntensity"] = json!(value.clamp(0., 1.));
        } else {
            self.config["zoomFactor"] = json!(value.clamp(1.25, 8.));
        }
    }
    pub fn reset_positions(&mut self) {
        for (i, f) in FEATURES.iter().enumerate() {
            if i < 5 {
                for suffix in ["X", "Y", "Scale"] {
                    self.config
                        .as_object_mut()
                        .unwrap()
                        .remove(&format!("{}{suffix}", f.0));
                }
            } else if let Some(v) = self.config["extraOverlays"][f.0].as_object_mut() {
                for key in ["x", "y", "scale"] {
                    v.remove(key);
                }
            }
        }
        self.config["scale"] = json!(1.);
        self.bounds = [[0.; 4]; 13];
    }
    pub fn save(&mut self) {
        let path = Game::game_dir().join("config/cubeon-client-hud.json");
        let temp = path.with_extension("json.tmp");
        let result = std::fs::create_dir_all(path.parent().unwrap())
            .and_then(|_| {
                std::fs::write(
                    &temp,
                    serde_json::to_vec_pretty(&self.config).unwrap_or_default(),
                )
            })
            .and_then(|_| std::fs::rename(&temp, &path));
        if let Err(error) = result {
            self.local_error = format!("Settings could not be saved: {error}");
        }
    }
    pub fn set_field(&mut self, id: Option<usize>) {
        self.field = id;
        for (i, field) in [
            &mut self.search,
            &mut self.composer,
            &mut self.add,
            &mut self.hex,
        ]
        .into_iter()
        .enumerate()
        {
            field.focused = id == Some(i);
            if field.focused {
                field.reset_blink();
            }
        }
    }
    pub fn active_field(&mut self) -> Option<&mut EditBox> {
        match self.field? {
            0 => Some(&mut self.search),
            1 => Some(&mut self.composer),
            2 => Some(&mut self.add),
            3 => Some(&mut self.hex),
            _ => None,
        }
    }
    pub fn remember_draft(&mut self) {
        if !self.peer.is_empty() && !self.account.is_empty() {
            if self.drafts.len() >= 32
                && !self
                    .drafts
                    .contains_key(&(self.account.clone(), self.peer.clone()))
            {
                if let Some(key) = self.drafts.keys().next().cloned() {
                    self.drafts.remove(&key);
                }
            }
            self.drafts.insert(
                (self.account.clone(), self.peer.clone()),
                self.composer.value.clone(),
            );
        }
    }
    pub fn notice(&mut self, text: String, error: bool) {
        if text.trim().is_empty()
            || self
                .notices
                .iter()
                .any(|n| n.text == text && n.born.elapsed().as_secs_f32() < 3.)
        {
            return;
        }
        while self.notices.len() >= 6 {
            self.notices.pop_front();
        }
        self.notices.push_back(Notice {
            text: text
                .chars()
                .take(512)
                .collect::<String>()
                .replace('\n', " "),
            error,
            born: Instant::now(),
        });
    }
    pub fn scroll(&mut self, d: f32, screen: Screen, cursor: (f32, f32)) -> bool {
        if self.open && screen == Screen::Friends {
            if self.tab == 4
                && let Some(i) = self.selected
            {
                self.set_scale(i, self.position(i).2 + d.signum() * 0.1);
                self.save();
            } else if matches!(self.tab, 2 | 3) {
                if art::contains(cursor, self.friend_rail) {
                    self.friend_offset = self
                        .friend_offset
                        .saturating_add_signed(-d.signum() as isize * 3);
                } else if self.manage_friends {
                    self.page = self.page.saturating_add_signed(-d.signum() as isize);
                } else {
                    self.transcript_scroll = (self.transcript_scroll + d.signum() * 36.)
                        .clamp(0., self.transcript_height);
                }
            } else if self.tab == 0 {
                self.page = self
                    .page
                    .saturating_add_signed(-d.signum() as isize)
                    .min(self.pages.saturating_sub(1));
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
impl Game<'_> {
    pub(super) fn cubeon_binding_down(&self, name: &str) -> bool {
        let key = self.settings.keys.get(name);
        cubeon_client::keybinds::key_code(key).is_some_and(|k| self.physical_keys.contains(&k))
            || cubeon_client::keybinds::mouse_button(key)
                .is_some_and(|b| self.physical_buttons.contains(&b))
    }
    fn cubeon_bound(&self, name: &str, key: KeyCode) -> bool {
        cubeon_client::keybinds::key_name(key) == Some(self.settings.keys.get(name))
    }
    pub(super) fn cubeon_open(&mut self, tab: usize) {
        if !self.companion.enabled {
            return;
        }
        let c = &mut self.companion;
        c.remember_draft();
        if !c.open {
            c.return_screen = self.screen;
            c.parents.clear();
        } else if c.tab != tab {
            c.parents.push(c.tab);
        }
        c.open = true;
        c.tab = tab;
        c.controls.clear();
        c.focus = None;
        c.set_field(None);
        c.drag = None;
        c.slider = None;
        c.opened = Instant::now();
        if tab == 0 {
            c.page = 0;
        }
        if tab == 2 {
            c.manage_friends = false;
        }
        if tab == 6 {
            c.theme_draft = c.theme;
            c.theme_custom = c.custom_palette;
            c.hex
                .set_value(&format!("{:06X}", c.theme_custom.0[c.role]));
        }
        self.screen = Screen::Friends;
    }
    pub(super) fn cubeon_back(&mut self) {
        let c = &mut self.companion;
        c.remember_draft();
        c.drag = None;
        c.slider = None;
        c.set_field(None);
        c.save();
        if c.tab == 8 {
            c.tab = 5;
            c.wheel_held = false;
        } else if let Some(tab) = c.parents.pop() {
            c.tab = tab;
        } else {
            c.bridge.chat(String::new());
            c.open = false;
            self.screen = c.return_screen;
        }
        c.controls.clear();
        c.focus = None;
        c.opened = Instant::now();
    }
    pub(super) fn cubeon_hit(&mut self, target: u32) {
        let c = &mut self.companion;
        c.combo = if c.combo_target == Some(target) && c.combo_at.elapsed().as_secs_f32() < 3. {
            c.combo.saturating_add(1)
        } else {
            1
        };
        c.combo_target = Some(target);
        c.combo_at = Instant::now();
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
        if self.screen != Screen::Friends && self.companion.open {
            self.companion.remember_draft();
            self.companion.open = false;
            self.companion.parents.clear();
            self.companion.bridge.chat(String::new());
        }
        let eligible = self.screen == Screen::Playing
            && !self.remote_loading()
            && self.title.is_none()
            && (self.focused || self.control.is_some())
            && !self.screen_over_playing()
            && self.player.is_some();
        let held = self.cubeon_binding_down("key.cubeon.freelook");
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
        let snapshot = self.companion.bridge.snapshot_arc();
        let metrics = self.companion.enabled(6) || (self.companion.open && self.companion.tab == 4);
        self.companion.bridge.metrics(metrics);
        self.cubeon_social_frame(&snapshot);
        self.cubeon_emotes_frame(&snapshot.emotes, eligible);
        if self.companion.combo_at.elapsed().as_secs_f32() > 3. {
            self.companion.combo = 0;
        }
        if let Some(renderer) = &mut self.renderer {
            renderer.fullbright =
                self.settings.extras.fullbright || self.companion.boolean("fullBright", false);
        }
        if self.screen != Screen::Friends
            || !self.companion.open
            || !matches!(self.companion.tab, 2 | 3)
            || self.companion.manage_friends
        {
            self.companion.bridge.chat(String::new());
        }
    }
    pub(super) fn cubeon_mouse_shortcut(
        &mut self,
        button: winit::event::MouseButton,
        pressed: bool,
    ) -> bool {
        if !self.companion.enabled || self.title.is_some() || self.remote_loading() {
            return false;
        }
        let key = cubeon_client::keybinds::mouse_name(button);
        if self.companion.open
            && matches!(self.companion.tab, 5 | 8)
            && self.settings.keys.get("key.cubeon.emotes") == key
        {
            return self.cubeon_emote_key(KeyCode::KeyB, pressed, false);
        }
        if !pressed
            || !matches!(self.screen, Screen::Playing | Screen::Paused)
            || self.screen_over_playing()
        {
            return false;
        }
        for (name, tab) in [
            ("key.cubeon.menu", 0),
            ("key.cubeon.chat", 2),
            ("key.cubeon.emotes", 5),
        ] {
            if self.settings.keys.get(name) == key {
                self.cubeon_open(tab);
                if tab == 5 {
                    self.companion.wheel_held = true;
                }
                return true;
            }
        }
        false
    }
    pub(super) fn cubeon_key(&mut self, key: KeyCode, pressed: bool, repeat: bool) -> bool {
        if !self.companion.enabled || (!self.companion.open && self.remote_loading()) {
            return false;
        }
        if pressed
            && !repeat
            && matches!(self.screen, Screen::Playing | Screen::Paused)
            && self.title.is_none()
            && !self.screen_over_playing()
        {
            if self.cubeon_bound("key.cubeon.menu", key)
                || key == KeyCode::ShiftRight && self.settings.keys.is_default("key.cubeon.menu")
            {
                self.cubeon_open(0);
                return true;
            }
            if self.cubeon_bound("key.cubeon.chat", key) {
                self.cubeon_open(2);
                return true;
            }
            if self.cubeon_bound("key.cubeon.emotes", key) {
                self.cubeon_open(5);
                self.companion.wheel_held = true;
                return true;
            }
        }
        if self.screen != Screen::Friends || !self.companion.open {
            return false;
        }
        if matches!(self.companion.tab, 5 | 8) {
            let key = if self.cubeon_bound("key.cubeon.emotes", key) {
                KeyCode::KeyB
            } else {
                key
            };
            return self.cubeon_emote_key(key, pressed, repeat);
        }
        if !pressed {
            return true;
        }
        let ctrl = self.has_control_down_with_quirk();
        let shift = self.modifiers.shift_key() || self.physical_keys.contains(&KeyCode::ShiftLeft);
        if key == KeyCode::Escape {
            if self.companion.field.is_some() && self.companion.tab == 0 {
                self.companion.set_field(None);
            } else {
                self.cubeon_back();
            }
            return true;
        }
        if key == KeyCode::Tab {
            if self.companion.field == Some(3) {
                self.cubeon_theme_color();
                if !self.companion.local_error.is_empty() {
                    return true;
                }
            }
            self.companion.set_field(None);
            let c = &mut self.companion;
            let count = c.controls.len();
            if count > 0 {
                let mut i = c.focus.unwrap_or(if shift { 0 } else { count - 1 });
                for _ in 0..count {
                    i = if shift {
                        (i + count - 1) % count
                    } else {
                        (i + 1) % count
                    };
                    if c.controls[i].enabled {
                        c.focus = Some(i);
                        break;
                    }
                }
            }
            return true;
        }
        if let Some(field) = self.companion.active_field() {
            use cubeon_client::clipboard::EditShortcut;
            if ctrl
                && matches!(
                    key,
                    KeyCode::KeyA | KeyCode::KeyC | KeyCode::KeyV | KeyCode::KeyX
                )
            {
                let shortcut = match key {
                    KeyCode::KeyC => EditShortcut::Copy,
                    KeyCode::KeyV => EditShortcut::Paste,
                    KeyCode::KeyX => EditShortcut::Cut,
                    _ => EditShortcut::SelectAll,
                };
                field.shortcut(shortcut, &mut self.clipboard);
            } else if key == KeyCode::Enter {
                match self.companion.field {
                    Some(1) => self.cubeon_input_send(),
                    Some(2) => self.cubeon_add_friend(),
                    Some(3) => self.cubeon_theme_color(),
                    _ => self.companion.set_field(None),
                }
            } else {
                field.key(key, ctrl, shift);
            }
            self.companion.remember_draft();
            if self.companion.tab == 0 {
                self.companion.page = 0;
            }
            return true;
        }
        if key == KeyCode::Slash && self.companion.tab == 0 {
            self.companion.set_field(Some(0));
            self.companion.search.set_value("");
            return true;
        }
        if key == KeyCode::Enter || key == KeyCode::Space {
            if let Some(control) = self
                .companion
                .focus
                .and_then(|i| self.companion.controls.get(i))
                .filter(|b| b.enabled)
                .cloned()
            {
                self.cubeon_action(control.action);
            }
        } else if matches!(key, KeyCode::ArrowLeft | KeyCode::ArrowRight) {
            let d = if key == KeyCode::ArrowLeft { -1. } else { 1. };
            if let Some(Control {
                action: Action::Scale(i),
                ..
            }) = self
                .companion
                .focus
                .and_then(|i| self.companion.controls.get(i))
            {
                let i = *i;
                let current = if i < 13 {
                    self.companion.position(i).2
                } else if i == 13 {
                    self.companion.number("cameraBlurIntensity", 1., 0., 1.)
                } else {
                    self.companion.number("zoomFactor", 4., 1.25, 8.)
                };
                self.companion.set_scale(i, current + d * 0.05);
                self.companion.save();
            } else if self.companion.tab == 4 && self.companion.selected.is_some() {
                self.cubeon_nudge(key, shift);
            } else {
                self.companion.page = self
                    .companion
                    .page
                    .saturating_add_signed(d as isize)
                    .min(self.companion.pages.saturating_sub(1));
            }
        } else if matches!(key, KeyCode::ArrowUp | KeyCode::ArrowDown) && self.companion.tab == 4 {
            self.cubeon_nudge(key, shift);
        }
        true
    }
    pub(super) fn cubeon_chars(&mut self, text: &str) {
        if self.screen == Screen::Friends
            && self.companion.open
            && let Some(field) = self.companion.active_field()
        {
            field.insert_text(text);
            self.companion.remember_draft();
            if self.companion.tab == 0 {
                self.companion.page = 0;
            }
        }
    }
    pub(super) fn cubeon_screen(&mut self, batch: &mut HudBatch) {
        cubeon_client::widgets::begin_screen(|| {
            cubeon_client::widgets::ScreenInfo::new("cubeon_client", "Cubeon Client")
        });
        self.companion.controls.clear();
        if matches!(self.companion.tab, 5 | 8) {
            self.cubeon_emote_wheel(batch);
            return;
        }
        if self.companion.tab == 4 {
            self.cubeon_hud(batch, true);
        } else {
            batch.fill(
                &self.gui.atlas,
                0.,
                0.,
                batch.width,
                batch.height,
                art::native_color(0x9309090c),
            );
        }
        match self.companion.tab {
            2 | 3 => self.cubeon_friends_screen(batch),
            4 => self.cubeon_editor(batch),
            6 => self.cubeon_themes(batch),
            _ => self.cubeon_menu(batch),
        }
        if let Some(field) = self.companion.active_field() {
            field.draw(batch, &self.gui.atlas, None);
        }
        if let Some(i) = self.companion.focus
            && let Some(control) = self.companion.controls.get(i)
        {
            let r = control.rect;
            let color = art::native_color(self.companion.palette.bright());
            batch.fill(&self.gui.atlas, r[0], r[1], r[2], 1., color);
            batch.fill(&self.gui.atlas, r[0], r[1] + r[3] - 1., r[2], 1., color);
        }
    }
    pub(super) fn cubeon_click(&mut self, right: bool) {
        if matches!(self.companion.tab, 5 | 8) {
            self.cubeon_emote_click(right);
            return;
        }
        if let Some(control) = self
            .companion
            .controls
            .iter()
            .find(|b| art::contains(self.cursor, b.rect))
            .cloned()
        {
            if !control.enabled {
                return;
            }
            self.companion.pointer_select = false;
            if let Action::Field(id) = control.action {
                self.companion.set_field(Some(id));
                let shift = self.modifiers.shift_key();
                if let Some(field) = self.companion.active_field() {
                    field.click(&self.gui.atlas, self.cursor.0, shift, false);
                }
                self.companion.pointer_select = true;
                return;
            }
            if self.companion.field == Some(3)
                && matches!(control.action, Action::Role(_) | Action::ApplyTheme)
            {
                self.cubeon_theme_color();
                if !self.companion.local_error.is_empty() {
                    return;
                }
            }
            self.companion.set_field(None);
            if let Action::Scale(i) = control.action {
                self.companion.slider = Some((i, control.rect));
                self.cubeon_drag(true);
                return;
            }
            self.cubeon_action(control.action);
            return;
        }
        self.companion.set_field(None);
        if self.companion.tab == 4 {
            for i in (0..13).rev() {
                let r = self.companion.bounds[i];
                if art::contains(self.cursor, r) {
                    self.companion.selected = Some(i);
                    if right {
                        self.companion.toggle(i);
                        self.companion.save();
                    } else {
                        self.companion.drag = Some((self.cursor.0 - r[0], self.cursor.1 - r[1]));
                    }
                    break;
                }
            }
        }
    }
    pub(super) fn cubeon_drag(&mut self, held: bool) {
        if !held {
            if self.companion.drag.take().is_some() || self.companion.slider.take().is_some() {
                self.companion.save();
            }
            self.companion.pointer_select = false;
            return;
        }
        if !self.companion.open {
            return;
        }
        if self.companion.pointer_select
            && let Some(field) = self.companion.active_field()
        {
            field.drag_to(&self.gui.atlas, self.cursor.0);
            self.companion.remember_draft();
            return;
        }
        if let Some((i, r)) = self.companion.slider {
            let fraction = ((self.cursor.0 - r[0] - 10.) / (r[2] - 20.).max(1.)).clamp(0., 1.);
            self.companion.set_scale(
                i,
                if i < 13 {
                    0.5 + fraction * 1.5
                } else if i == 13 {
                    fraction
                } else {
                    1.25 + fraction * 6.75
                },
            );
            return;
        }
        if self.companion.tab == 4
            && let Some(i) = self.companion.selected
            && let Some((dx, dy)) = self.companion.drag
        {
            let (w, h) = self.gui_size();
            let r = self.companion.bounds[i];
            self.cubeon_position(
                i,
                ((self.cursor.0 - dx) / (w - r[2]).max(1.)).clamp(0., 1.),
                ((self.cursor.1 - dy) / (h - r[3]).max(1.)).clamp(0., 1.),
            );
        }
    }
    fn cubeon_position(&mut self, i: usize, x: f32, y: f32) {
        let slot = FEATURES[i].0;
        if i < 5 {
            self.companion.config[format!("{slot}X")] = json!(x);
            self.companion.config[format!("{slot}Y")] = json!(y);
        } else {
            self.companion.config["extraOverlays"][slot]["x"] = json!(x);
            self.companion.config["extraOverlays"][slot]["y"] = json!(y);
        }
    }
    fn cubeon_nudge(&mut self, key: KeyCode, large: bool) {
        let Some(i) = self.companion.selected else {
            return;
        };
        let (x, y, _) = self.companion.position(i);
        let (w, h) = self.gui_size();
        let step = if large { 10. } else { 1. };
        self.cubeon_position(
            i,
            (x + match key {
                KeyCode::ArrowLeft => -step / w,
                KeyCode::ArrowRight => step / w,
                _ => 0.,
            })
            .clamp(0., 1.),
            (y + match key {
                KeyCode::ArrowUp => -step / h,
                KeyCode::ArrowDown => step / h,
                _ => 0.,
            })
            .clamp(0., 1.),
        );
        self.companion.save();
    }
}
