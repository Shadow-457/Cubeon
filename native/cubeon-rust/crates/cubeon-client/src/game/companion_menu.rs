//! Fabric's searchable K catalogue, themes and HUD editor.
use super::{
    Game,
    companion::{Action, Companion, Control, FEATURES},
};
use cubeon_client::{hud::HudBatch, widgets};
use cubeon_client_render::cubeon_ui::{self as art, Canvas, PRESETS, Palette, ROLES, THEME_NAMES};
use serde_json::json;

impl Companion {
    pub fn register(&mut self, action: Action, r: [f32; 4], label: &str, enabled: bool) {
        let kind = if let Action::Field(_) = action {
            widgets::Kind::Field
        } else if let Action::Scale(i) = action {
            let value = if i < 13 {
                (self.position(i).2 - 0.5) / 1.5
            } else if i == 13 {
                self.number("cameraBlurIntensity", 1., 0., 1.)
            } else {
                (self.number("zoomFactor", 4., 1.25, 8.) - 1.25) / 6.75
            };
            widgets::Kind::Slider {
                value,
                track: [r[0] + 10., r[2] - 20.],
            }
        } else {
            widgets::Kind::Button
        };
        widgets::record_as(label, r, enabled, kind);
        widgets::target_as(r, kind);
        widgets::narratable(|| widgets::Narratable::button(label, r, enabled));
        self.controls.push(Control {
            action,
            rect: r,
            label: label.into(),
            enabled,
        });
    }
    pub fn button(
        &mut self,
        canvas: &mut Canvas<'_>,
        cursor: (f32, f32),
        action: Action,
        r: [f32; 4],
        label: &str,
        enabled: bool,
        primary: bool,
    ) {
        let hover = art::contains(cursor, r) || self.focus == Some(self.controls.len());
        canvas.button(r, label, hover, primary, enabled);
        self.register(action, r, label, enabled);
    }
}
fn panel(w: f32, h: f32) -> [f32; 4] {
    let pw = (w - 32.).min(560.).min((w * 0.8).max(288.)).max(120.);
    let ph = (h - 24.).min(320.).min((h * 0.78).max(216.)).max(120.);
    [(w - pw) / 2., (h - ph) / 2., pw, ph]
}
impl Game<'_> {
    pub(super) fn cubeon_menu(&mut self, batch: &mut HudBatch) {
        let [x, y, w, h] = panel(batch.width, batch.height);
        let cursor = self.cursor;
        let c = &mut self.companion;
        let p = c.palette;
        let fade = if c.boolean("menuAnimations", true) {
            (c.opened.elapsed().as_secs_f32() / 0.22).min(1.)
        } else {
            1.
        };
        let mut ui = Canvas {
            batch,
            atlas: &self.gui.atlas,
            palette: p,
            fade,
        };
        ui.pixel([x, y, w, h], p.surface(), p.rim());
        let tool_x = x + w - 10. - 116.;
        ui.text(
            &art::fit(
                ui.atlas,
                &art::tr("menu.title"),
                (tool_x - x - 44.).max(10.),
            ),
            x + 38.,
            y + 14.,
            p.text(),
        );
        for (position, (index, action, label)) in [
            (0, Action::Open(4), "HUD editor"),
            (1, Action::Open(6), "Themes"),
            (3, Action::Reset, "Reset positions and scales"),
            (4, Action::Open(5), "Emotes"),
            (5, Action::Open(2), "Friends"),
            (6, Action::Close, "Done"),
        ]
        .into_iter()
        .enumerate()
        {
            let r = if position == 0 {
                [x + 10., y + 8., 20., 20.]
            } else {
                [tool_x + (position - 1) as f32 * 24., y + 8., 20., 20.]
            };
            ui.tool(
                index,
                r,
                art::contains(cursor, r) || c.focus == Some(c.controls.len()),
            );
            c.register(action, r, label, true);
        }
        if c.tab == 1 {
            let (slot, _) = Companion::feature(c.detail);
            let label = art::tr(&format!("hud.{slot}"));
            c.button(
                &mut ui,
                cursor,
                Action::Back,
                [x + 12., y + 40., 72., 22.],
                "Back",
                true,
                false,
            );
            ui.text(
                &art::fit(ui.atlas, &label, w - 110.),
                x + 94.,
                y + 47.,
                p.text(),
            );
            for (i, line) in cubeon_client::multiplayer::wrap(
                &art::tr(&format!("hud.{slot}_hint")),
                w - 24.,
                ui.atlas,
            )
            .iter()
            .take(2)
            .enumerate()
            {
                ui.text(line, x + 12., y + 77. + i as f32 * 10., p.dim());
            }
            let on = c.feature_enabled(c.detail);
            c.button(
                &mut ui,
                cursor,
                Action::Toggle(c.detail),
                [x + 12., y + 105., (w - 30.) / 2., 24.],
                if on { "Enabled" } else { "Disabled" },
                true,
                on,
            );
            if c.detail < 13 {
                let i = c.detail;
                let scale = c.position(i).2;
                let r = [x + 12., y + 139., w - 24., 30.];
                draw_slider(
                    &mut ui,
                    c,
                    cursor,
                    Action::Scale(i),
                    r,
                    &format!("Scale: {:.0}%", scale * 100.),
                    (scale - 0.5) / 1.5,
                );
                if slot == "clock" {
                    c.button(
                        &mut ui,
                        cursor,
                        Action::Setting("worldClock", false),
                        [x + 12., y + 181., w - 24., 24.],
                        if c.boolean("worldClock", false) {
                            "World time"
                        } else {
                            "System time"
                        },
                        true,
                        false,
                    );
                }
                if slot == "armor" {
                    let keys = [
                        "showArmorHelmet",
                        "showArmorChest",
                        "showArmorLegs",
                        "showArmorFeet",
                    ];
                    for (i, key) in keys.iter().enumerate() {
                        let r = [
                            x + 12. + i as f32 * (w - 24.) / 4.,
                            y + 181.,
                            (w - 24.) / 4. - 3.,
                            24.,
                        ];
                        let on = c.boolean(key, true);
                        c.button(
                            &mut ui,
                            cursor,
                            Action::Setting(key, true),
                            r,
                            ["Helmet", "Chest", "Legs", "Boots"][i],
                            true,
                            on,
                        );
                    }
                }
            } else if slot == "camera_blur" {
                let value = c.number("cameraBlurIntensity", 1., 0., 1.);
                draw_slider(
                    &mut ui,
                    c,
                    cursor,
                    Action::Scale(13),
                    [x + 12., y + 139., w - 24., 36.],
                    &format!("Blur intensity: {:.0}%", value * 100.),
                    value,
                );
            } else if slot == "sprint" {
                ui.text(
                    "Respects hunger, sneaking, item use and collision.",
                    x + 12.,
                    y + 144.,
                    p.dim(),
                );
            }
            let value = c.number("zoomFactor", 4., 1.25, 8.);
            if h >= 270. {
                draw_slider(
                    &mut ui,
                    c,
                    cursor,
                    Action::Scale(14),
                    [x + 12., y + h - 64., w - 24., 30.],
                    &format!("Zoom: {value:.1}×"),
                    (value - 1.25) / 6.75,
                );
            }
        } else {
            let search = [x + 12., y + 36., w - 24., 22.];
            ui.pixel(
                search,
                p.cards(),
                if c.field == Some(0) {
                    p.accent()
                } else {
                    p.border()
                },
            );
            c.search.x = search[0] + 8.;
            c.search.y = search[1] + 7.;
            c.search.width = search[2] - 16.;
            c.search.height = 9.;
            c.search.text_color = art::native_color(p.text());
            if c.search.value.is_empty() && c.field != Some(0) {
                ui.text(
                    "Search features…",
                    search[0] + 8.,
                    search[1] + 7.,
                    p.faint(),
                );
            } else if c.field != Some(0) {
                c.search.draw(ui.batch, ui.atlas, None);
            }
            c.register(Action::Field(0), search, "Search features", true);
            for (i, label) in ["All", "HUD", "Player", "Render", "Movement"]
                .iter()
                .enumerate()
            {
                let cw = (w - 40.) / 5.;
                let r = [x + 12. + i as f32 * (cw + 4.), y + 64., cw, 20.];
                let selected = c.category == i;
                ui.pixel(
                    r,
                    if selected { p.selected() } else { p.surface() },
                    if selected { p.rim() } else { p.border() },
                );
                ui.center(
                    &art::fit(ui.atlas, label, cw - 8.),
                    r[0] + cw / 2.,
                    r[1] + 6.,
                    if selected { p.bright() } else { p.dim() },
                );
                c.register(Action::Category(i), r, label, true);
            }
            let needle = c.search.value.trim().to_lowercase();
            let filtered: Vec<_> = (0..19)
                .filter(|&i| {
                    let (slot, category) = Companion::feature(i);
                    let label = art::tr(&format!("hud.{slot}"));
                    (c.category == 0
                        || category == ["All", "HUD", "Player", "Render", "Movement"][c.category])
                        && (needle.is_empty()
                            || format!("{label} {slot} {category}")
                                .to_lowercase()
                                .contains(&needle))
                })
                .collect();
            let available = w - 24.;
            let cols = if available < 320. { 1 } else { 2 };
            let top = y + 90.;
            let pager = y + h - 28.;
            let room = (pager - top - 6.).max(34.);
            let rows = (((room + 6.) / 48.).floor() as usize).clamp(1, 4);
            let capacity = cols * rows;
            c.pages = filtered.len().div_ceil(capacity).max(1);
            c.page = c.page.min(c.pages - 1);
            let cw = (available - (cols - 1) as f32 * 8.) / cols as f32;
            let ch = ((room - (rows - 1) as f32 * 6.) / rows as f32).min(46.);
            for (j, i) in filtered
                .iter()
                .skip(c.page * capacity)
                .take(capacity)
                .enumerate()
            {
                let i = *i;
                let r = [
                    x + 12. + (j % cols) as f32 * (cw + 8.),
                    top + (j / cols) as f32 * (ch + 6.),
                    cw,
                    ch,
                ];
                let on = c.feature_enabled(i);
                let hover = art::contains(cursor, r);
                ui.pixel(
                    r,
                    if on {
                        art::mix(p.cards(), p.accent(), 0.32)
                    } else {
                        p.surface()
                    },
                    if on {
                        p.accent()
                    } else if hover {
                        p.dim()
                    } else {
                        p.border()
                    },
                );
                ui.icon(i, [r[0] + 8., r[1] + (ch - 20.) / 2., 20., 20.], on);
                let label = art::tr(&format!("hud.{}", Companion::feature(i).0));
                ui.text(
                    &art::fit(ui.atlas, &label, cw - 74.),
                    r[0] + 36.,
                    r[1] + (ch - 9.) / 2.,
                    if on { p.text() } else { p.dim() },
                );
                c.register(
                    Action::Toggle(i),
                    [r[0], r[1], cw - 28., ch],
                    &format!("{label}: {}", if on { "On" } else { "Off" }),
                    true,
                );
                let gear = [r[0] + cw - 23., r[1] + (ch - 18.) / 2., 18., 18.];
                ui.gear(gear, art::contains(cursor, gear));
                c.register(Action::Detail(i), gear, &format!("{label} settings"), true);
            }
            if filtered.is_empty() {
                ui.center("No matching features", x + w / 2., y + h / 2., p.dim());
            }
            c.button(
                &mut ui,
                cursor,
                Action::Page(-1),
                [x + 12., pager, 28., 20.],
                "‹",
                c.page > 0,
                false,
            );
            c.button(
                &mut ui,
                cursor,
                Action::Page(1),
                [x + w - 40., pager, 28., 20.],
                "›",
                c.page + 1 < c.pages,
                false,
            );
            ui.center(
                &format!("{} / {}", c.page + 1, c.pages),
                x + w / 2.,
                pager + 6.,
                p.faint(),
            );
        }
        if let Some(control) = c.controls.iter().find(|b| art::contains(cursor, b.rect))
            && matches!(
                control.action,
                Action::Open(_) | Action::Close | Action::Reset
            )
        {
            let text = art::fit(ui.atlas, &control.label, w - 24.);
            let tw = HudBatch::text_width(ui.atlas, &text) + 12.;
            ui.panel(
                [
                    cursor.0.min(ui.batch.width - tw - 2.),
                    (y - 24.).max(2.),
                    tw,
                    20.,
                ],
                p.cards(),
                p.rim(),
            );
            ui.text(
                &text,
                cursor.0.min(ui.batch.width - tw - 2.) + 6.,
                (y - 24.).max(2.) + 6.,
                p.text(),
            );
        }
    }
    pub(super) fn cubeon_themes(&mut self, batch: &mut HudBatch) {
        let [x, y, w, h] = panel(batch.width, batch.height);
        let cursor = self.cursor;
        let c = &mut self.companion;
        let p = if c.theme_draft < 5 {
            Palette(PRESETS[c.theme_draft])
        } else {
            c.theme_custom
        };
        let mut ui = Canvas {
            batch,
            atlas: &self.gui.atlas,
            palette: p,
            fade: 1.,
        };
        ui.pixel([x, y, w, h], p.surface(), p.rim());
        ui.mark(x + 12., y + 10.);
        ui.text("Client themes", x + 40., y + 16., p.text());
        c.button(
            &mut ui,
            cursor,
            Action::Back,
            [x + w - 80., y + 10., 68., 20.],
            "Back",
            true,
            false,
        );
        let cw = (w - 32.) / 3.;
        for (i, name) in THEME_NAMES.iter().enumerate() {
            let r = [
                x + 12. + (i % 3) as f32 * (cw + 4.),
                y + 42. + (i / 3) as f32 * 30.,
                cw,
                26.,
            ];
            c.button(
                &mut ui,
                cursor,
                Action::Theme(i),
                r,
                name,
                true,
                c.theme_draft == i,
            );
        }
        let roomy = h >= 280.;
        if roomy {
            ui.text("Preview", x + 12., y + 113., p.dim());
            ui.pixel([x + 12., y + 129., w * 0.46, 56.], p.cards(), p.border());
            ui.icon(0, [x + 20., y + 144., 20., 20.], true);
            ui.text("Cubeon Client", x + 48., y + 145., p.text());
            ui.text("Your menu colors", x + 48., y + 161., p.dim());
        }
        let right = if roomy { x + 28. + w * 0.46 } else { x + 12. };
        let rw = x + w - 12. - right;
        let cols = if roomy { 2 } else { 3 };
        for (i, role) in ROLES.iter().enumerate() {
            let r = [
                right + (i % cols) as f32 * (rw + 4.) / cols as f32,
                y + 106. + (i / cols) as f32 * 24.,
                (rw - 4. * (cols - 1) as f32) / cols as f32,
                20.,
            ];
            c.button(&mut ui, cursor, Action::Role(i), r, role, true, c.role == i);
        }
        let r = [x + 12., y + h - if roomy { 78. } else { 54. }, w - 24., 22.];
        ui.pixel(r, p.cards(), p.rim());
        ui.text(
            &format!("{}  #", ROLES[c.role]),
            r[0] + 8.,
            r[1] + 7.,
            p.dim(),
        );
        let tx = r[0] + HudBatch::text_width(ui.atlas, &format!("{}  #", ROLES[c.role])) + 12.;
        c.hex.x = tx;
        c.hex.y = r[1] + 7.;
        c.hex.width = (r[2] - (tx - r[0]) - 8.).max(36.);
        c.hex.height = 9.;
        c.hex.text_color = art::native_color(p.text());
        if c.field != Some(3) {
            c.hex.draw(ui.batch, ui.atlas, None);
        }
        c.register(Action::Field(3), r, "Custom hex color", true);
        if !c.local_error.is_empty() {
            ui.text(
                &art::fit(ui.atlas, &c.local_error, w - 24.),
                x + 12.,
                y + h - if roomy { 49. } else { 65. },
                0xffff9c89,
            );
        }
        c.button(
            &mut ui,
            cursor,
            Action::ApplyTheme,
            [x + 12., y + h - if roomy { 32. } else { 28. }, w - 24., 20.],
            "Apply theme",
            true,
            true,
        );
    }
    pub(super) fn cubeon_theme_color(&mut self) {
        let c = &mut self.companion;
        if c.hex.value.len() == 6 && c.hex.value.bytes().all(|v| v.is_ascii_hexdigit()) {
            c.theme_custom.0[c.role] = u32::from_str_radix(&c.hex.value, 16).unwrap();
            c.theme_draft = 5;
            c.local_error.clear();
            c.set_field(None);
        } else {
            c.local_error = "Enter six hexadecimal digits, for example 83C13D.".into();
        }
    }
    pub(super) fn cubeon_editor(&mut self, batch: &mut HudBatch) {
        let c = &mut self.companion;
        let cursor = self.cursor;
        let p = c.palette;
        let w = (batch.width - 16.).min(440.);
        let x = (batch.width - w) / 2.;
        let y = batch.height - 60.;
        let mut ui = Canvas {
            batch,
            atlas: &self.gui.atlas,
            palette: p,
            fade: 1.,
        };
        ui.pixel([x, y, w, 52.], p.surface(), p.rim());
        let name = c
            .selected
            .map(|i| art::tr(&format!("hud.{}", FEATURES[i].0)))
            .unwrap_or_else(|| "Select an overlay".into());
        ui.text(
            &art::fit(
                ui.atlas,
                &format!("{name} · drag to move · scroll to resize"),
                w - 16.,
            ),
            x + 8.,
            y + 8.,
            p.text(),
        );
        c.button(
            &mut ui,
            cursor,
            Action::Reset,
            [x + 8., y + 25., 110., 20.],
            "Reset layout",
            true,
            false,
        );
        if let Some(i) = c.selected {
            c.button(
                &mut ui,
                cursor,
                Action::Toggle(i),
                [x + 124., y + 25., 110., 20.],
                if c.enabled(i) { "Enabled" } else { "Disabled" },
                true,
                c.enabled(i),
            );
        }
        c.button(
            &mut ui,
            cursor,
            Action::Back,
            [x + w - 86., y + 25., 78., 20.],
            "Done",
            true,
            true,
        );
    }
    pub(super) fn cubeon_action(&mut self, action: Action) {
        match action {
            Action::Toggle(i) => {
                self.companion.toggle(i);
                if i == 14 {
                    self.companion.config["temporalMotionBlur"] = json!(false);
                }
                self.companion.save();
            }
            Action::Detail(i) => {
                self.companion.detail = i;
                self.cubeon_open(1);
            }
            Action::Category(i) => {
                self.companion.category = i;
                self.companion.page = 0;
            }
            Action::Page(d) => {
                if matches!(self.companion.tab, 2 | 3) {
                    self.cubeon_social_action(Action::Page(d));
                } else {
                    self.companion.page = self
                        .companion
                        .page
                        .saturating_add_signed(d as isize)
                        .min(self.companion.pages.saturating_sub(1));
                }
            }
            Action::Open(tab) => {
                self.cubeon_open(tab);
                if tab == 5 {
                    self.companion.wheel_held = false;
                }
            }
            Action::Back => self.cubeon_back(),
            Action::Close => {
                self.companion.parents.clear();
                self.cubeon_back();
            }
            Action::Reset => {
                self.companion.reset_positions();
                self.companion.save();
            }
            Action::Field(id) => self.companion.set_field(Some(id)),
            Action::Setting(key, default) => {
                let value = !self.companion.boolean(key, default);
                self.companion.config[key] = json!(value);
                self.companion.save();
            }
            Action::Theme(i) => {
                self.companion.theme_draft = i;
                self.companion.local_error.clear();
            }
            Action::Role(i) => {
                self.cubeon_theme_color_if_valid();
                let c = &mut self.companion;
                c.role = i;
                c.hex.set_value(&format!("{:06X}", c.theme_custom.0[i]));
            }
            Action::ApplyTheme => {
                if self.companion.field == Some(3) {
                    self.cubeon_theme_color();
                    if !self.companion.local_error.is_empty() {
                        return;
                    }
                }
                let c = &mut self.companion;
                match c.theme_custom.save(&Game::game_dir(), c.theme_draft) {
                    Ok(()) => {
                        c.theme = c.theme_draft;
                        c.custom_palette = c.theme_custom;
                        c.palette = if c.theme < 5 {
                            Palette(PRESETS[c.theme])
                        } else {
                            c.custom_palette
                        };
                        c.local_error.clear();
                        self.cubeon_back();
                    }
                    Err(e) => c.local_error = e,
                }
            }
            other => self.cubeon_social_action(other),
        }
    }
    fn cubeon_theme_color_if_valid(&mut self) {
        if self.companion.hex.value.len() == 6 && self.companion.field == Some(3) {
            self.cubeon_theme_color();
        }
    }
}
fn draw_slider(
    ui: &mut Canvas<'_>,
    c: &mut Companion,
    cursor: (f32, f32),
    action: Action,
    r: [f32; 4],
    label: &str,
    value: f32,
) {
    ui.pixel(
        r,
        ui.palette.cards(),
        if art::contains(cursor, r) {
            ui.palette.rim()
        } else {
            ui.palette.border()
        },
    );
    ui.text(label, r[0] + 10., r[1] + 5., ui.palette.dim());
    let y = r[1] + r[3] - 10.;
    ui.fill([r[0] + 10., y, r[2] - 20., 3.], ui.palette.border());
    ui.fill(
        [r[0] + 10., y, (r[2] - 20.) * value.clamp(0., 1.), 3.],
        ui.palette.accent(),
    );
    ui.fill(
        [
            r[0] + 8. + (r[2] - 20.) * value.clamp(0., 1.),
            y - 2.,
            4.,
            7.,
        ],
        ui.palette.text(),
    );
    c.register(action, r, label, true);
}
