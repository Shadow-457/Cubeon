//! Fabric's client artwork, palette and small drawing primitives on the native HUD.
//! The sources are embedded from the shared client, so the two clients use one artwork.
use crate::{
    hud::{HudAtlas, HudBatch},
    ui,
};
use std::{path::Path, sync::OnceLock};

pub const PRESETS: [[u32; 6]; 5] = [
    [0x83C13D, 0x12161B, 0x1A2027, 0x303943, 0xE6EDF3, 0xA8B3C0],
    [0xE7A4C5, 0x171B19, 0x232D27, 0x425C4A, 0xF1F5EA, 0xB5C7B7],
    [0xF5CE68, 0x111E24, 0x19313B, 0x355561, 0xF7F2DA, 0xA9CAD2],
    [0xEAA060, 0x211916, 0x30231D, 0x634535, 0xF5EADD, 0xC9B4A2],
    [0x9BCDF3, 0x141B29, 0x202C40, 0x3D506D, 0xEDF5FF, 0xAFBFD5],
];
pub const THEME_NAMES: [&str; 6] = ["Default", "Spring", "Summer", "Autumn", "Winter", "Custom"];
pub const ROLES: [&str; 6] = [
    "Accent",
    "Background",
    "Cards",
    "Border",
    "Text",
    "Muted text",
];
#[derive(Clone, Copy, Debug)]
pub struct Palette(pub [u32; 6]);
impl Default for Palette {
    fn default() -> Self {
        Self(PRESETS[0])
    }
}
impl Palette {
    pub fn accent(self) -> u32 {
        self.0[0] | 0xff000000
    }
    pub fn surface(self) -> u32 {
        self.0[1] | 0xff000000
    }
    pub fn cards(self) -> u32 {
        self.0[2] | 0xff000000
    }
    pub fn border(self) -> u32 {
        self.0[3] | 0xff000000
    }
    pub fn text(self) -> u32 {
        self.0[4] | 0xff000000
    }
    pub fn dim(self) -> u32 {
        self.0[5] | 0xff000000
    }
    pub fn selected(self) -> u32 {
        mix(self.cards(), self.accent(), 0.15)
    }
    pub fn rim(self) -> u32 {
        mix(self.border(), self.accent(), 0.55)
    }
    pub fn bright(self) -> u32 {
        mix(self.accent(), self.text(), 0.35)
    }
    pub fn faint(self) -> u32 {
        mix(self.surface(), self.dim(), 0.72)
    }
    pub fn load(root: &Path) -> (usize, Self) {
        let mut selected = 0;
        let mut custom = PRESETS[0];
        if let Ok(text) =
            std::fs::read_to_string(root.join("config/cubeon-client-theme.properties"))
        {
            if text.len() <= 8192 {
                for line in text.lines() {
                    if let Some((key, value)) = line.split_once('=') {
                        let (key, value) = (key.trim(), value.trim());
                        if key == "theme" {
                            selected = THEME_NAMES
                                .iter()
                                .position(|n| n.eq_ignore_ascii_case(value))
                                .or_else(|| value.parse().ok())
                                .unwrap_or(0)
                                .min(5);
                        }
                        for i in 0..6 {
                            if key == format!("color.{i}")
                                && value.len() == 6
                                && let Ok(color) = u32::from_str_radix(value, 16)
                            {
                                custom[i] = color;
                            }
                        }
                    }
                }
            }
        }
        (selected, Self(custom))
    }
    pub fn save(self, root: &Path, selected: usize) -> Result<(), String> {
        let path = root.join("config/cubeon-client-theme.properties");
        let temp = path.with_extension("properties.tmp");
        let mut data = format!("theme={}\n", selected.min(5));
        for i in 0..6 {
            data.push_str(&format!("color.{i}={:06X}\n", self.0[i] & 0xffffff));
        }
        std::fs::create_dir_all(path.parent().unwrap())
            .and_then(|_| std::fs::write(&temp, data))
            .and_then(|_| std::fs::rename(&temp, &path))
            .map_err(|e| format!("Theme could not be saved: {e}"))
    }
}
pub fn mix(from: u32, to: u32, t: f32) -> u32 {
    let mut result = 0;
    for shift in [0, 8, 16, 24] {
        let value = (((from >> shift) & 255) as f32 * (1. - t) + ((to >> shift) & 255) as f32 * t)
            .round() as u32;
        result |= value.min(255) << shift;
    }
    result
}
pub fn alpha(color: u32, fade: f32) -> u32 {
    color & 0xffffff | ((((color >> 24) as f32 * fade.clamp(0., 1.)).round() as u32) << 24)
}
/// Java artwork/palettes are ARGB; HudBatch's packed vertex colour is ABGR.
pub fn native_color(argb: u32) -> u32 {
    (argb & 0xff00ff00) | ((argb & 0xff) << 16) | ((argb >> 16) & 0xff)
}
pub fn contains(cursor: (f32, f32), rect: [f32; 4]) -> bool {
    ui::hovered(cursor, rect[0], rect[1], rect[2], rect[3])
}
pub fn fit(atlas: &HudAtlas, value: &str, width: f32) -> String {
    if HudBatch::text_width(atlas, value) <= width {
        return value.into();
    }
    let mut result = String::new();
    for c in value.chars() {
        let next = format!("{result}{c}…");
        if HudBatch::text_width(atlas, &next) > width {
            break;
        }
        result.push(c);
    }
    if !result.is_empty() {
        result.push('…');
    }
    result
}
pub fn tr(slot: &str) -> String {
    static LANG: OnceLock<serde_json::Value> = OnceLock::new();
    let language = LANG.get_or_init(|| {
        serde_json::from_str(include_str!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/lang/en_us.json"
        ))
        .unwrap_or_default()
    });
    let key = format!("cubeonclient.{slot}");
    language[&key].as_str().unwrap_or(slot).to_owned()
}

pub struct Canvas<'a> {
    pub batch: &'a mut HudBatch,
    pub atlas: &'a HudAtlas,
    pub palette: Palette,
    pub fade: f32,
}
impl Canvas<'_> {
    pub fn fill(&mut self, r: [f32; 4], color: u32) {
        self.batch.fill(
            self.atlas,
            r[0],
            r[1],
            r[2].max(0.),
            r[3].max(0.),
            native_color(alpha(color, self.fade)),
        );
    }
    pub fn text(&mut self, value: &str, x: f32, y: f32, color: u32) {
        self.batch.text(
            self.atlas,
            value,
            x,
            y,
            native_color(alpha(color, self.fade)),
            false,
        );
    }
    pub fn center(&mut self, value: &str, x: f32, y: f32, color: u32) {
        self.text(
            value,
            x - HudBatch::text_width(self.atlas, value) / 2.,
            y,
            color,
        );
    }
    pub fn pixel(&mut self, [x, y, w, h]: [f32; 4], fill: u32, border: u32) {
        if w < 4. || h < 4. {
            return;
        }
        self.fill([x, y, w, h], border);
        self.fill([x + 2., y + 2., w - 4., h - 4.], fill);
        self.fill(
            [x + 2., y + 2., w - 4., 2.],
            mix(fill, self.palette.text(), 0.16),
        );
        self.fill(
            [x + 2., y + h - 4., w - 4., 2.],
            mix(fill, 0xff000000, 0.35),
        );
    }
    pub fn image(&mut self, name: &str, r: [f32; 4], uv: [f32; 4], color: u32) {
        if let Some(mut sprite) = self.atlas.sprites.get(name).copied() {
            let (u, v, w, h) = (
                sprite.u0,
                sprite.v0,
                sprite.u1 - sprite.u0,
                sprite.v1 - sprite.v0,
            );
            sprite.u0 = u + w * uv[0];
            sprite.v0 = v + h * uv[1];
            sprite.u1 = u + w * uv[2];
            sprite.v1 = v + h * uv[3];
            self.batch.rect_uv(
                r[0],
                r[1],
                r[2],
                r[3],
                sprite,
                native_color(alpha(color, self.fade)),
            );
        }
    }
    fn rounded(&mut self, [x, y, w, h]: [f32; 4], radius: f32, color: u32) {
        let r = radius.min(6.).min(w / 2.).min(h / 2.).max(0.);
        if r < 1. {
            self.fill([x, y, w, h], color);
            return;
        }
        self.fill([x + r, y, w - 2. * r, h], color);
        self.fill([x, y + r, r, h - 2. * r], color);
        self.fill([x + w - r, y + r, r, h - 2. * r], color);
        for dy in 0..2 {
            for dx in 0..2 {
                self.image(
                    "cubeon/ui/rounded",
                    [x + dx as f32 * (w - r), y + dy as f32 * (h - r), r, r],
                    [
                        dx as f32 / 2.,
                        dy as f32 / 2.,
                        (dx + 1) as f32 / 2.,
                        (dy + 1) as f32 / 2.,
                    ],
                    color,
                );
            }
        }
    }
    pub fn panel(&mut self, r: [f32; 4], fill: u32, border: u32) {
        self.rounded(r, 6., border);
        self.rounded([r[0] + 1., r[1] + 1., r[2] - 2., r[3] - 2.], 5., fill);
    }
    pub fn button(&mut self, r: [f32; 4], value: &str, hover: bool, primary: bool, enabled: bool) {
        let p = self.palette;
        self.pixel(
            r,
            if hover && enabled {
                p.selected()
            } else {
                p.cards()
            },
            if primary && enabled {
                p.accent()
            } else if hover && enabled {
                p.rim()
            } else {
                p.border()
            },
        );
        self.center(
            &fit(self.atlas, value, r[2] - 12.),
            r[0] + r[2] / 2.,
            r[1] + (r[3] - 9.) / 2.,
            if enabled {
                if primary || hover { p.text() } else { p.dim() }
            } else {
                p.faint()
            },
        );
    }
    pub fn mark(&mut self, x: f32, y: f32) {
        self.image(
            "cubeon/client-logo",
            [x, y, 20., 20.],
            [0., 0., 1., 1.],
            0xffffffff,
        );
    }
    pub fn icon(&mut self, feature: usize, r: [f32; 4], on: bool) {
        let feature = if feature >= 17 { feature + 3 } else { feature };
        let art = if feature == 15 {
            11
        } else if feature > 15 {
            feature - 1
        } else {
            feature
        };
        self.pixels(
            0,
            art,
            r,
            if on {
                self.palette.bright()
            } else {
                self.palette.faint()
            },
        );
    }
    pub fn tool(&mut self, index: usize, r: [f32; 4], hover: bool) {
        self.pixel(
            r,
            if hover {
                self.palette.selected()
            } else {
                self.palette.cards()
            },
            if hover {
                self.palette.rim()
            } else {
                self.palette.border()
            },
        );
        self.pixels(
            1,
            index,
            r,
            if hover {
                self.palette.bright()
            } else {
                self.palette.dim()
            },
        );
    }
    pub fn gear(&mut self, r: [f32; 4], hover: bool) {
        self.pixel(
            r,
            self.palette.surface(),
            if hover {
                self.palette.rim()
            } else {
                self.palette.border()
            },
        );
        self.pixels(
            2,
            0,
            r,
            if hover {
                self.palette.bright()
            } else {
                self.palette.dim()
            },
        );
    }
    fn pixels(&mut self, group: usize, index: usize, r: [f32; 4], color: u32) {
        static ART: OnceLock<[Vec<[u16; 16]>; 3]> = OnceLock::new();
        let art = ART.get_or_init(|| {
            let source =
                include_str!("../../../../../mod/src/main/java/com/cubeon/client/ui/HudIcon.java");
            let sections = [
                source
                    .split("private static final String[][] ART=")
                    .nth(1)
                    .unwrap_or("")
                    .split("private static final String[][] TOOLS=")
                    .next()
                    .unwrap_or(""),
                source
                    .split("private static final String[][] TOOLS=")
                    .nth(1)
                    .unwrap_or("")
                    .split("private HudIcon()")
                    .next()
                    .unwrap_or(""),
                source
                    .split("private static final String[] GEAR =")
                    .nth(1)
                    .unwrap_or("")
                    .split("public static void gear")
                    .next()
                    .unwrap_or(""),
            ];
            sections.map(|section| {
                let rows: Vec<u16> = section
                    .split('"')
                    .filter(|s| s.len() == 16 && s.bytes().all(|b| b == b'0' || b == b'1'))
                    .filter_map(|s| u16::from_str_radix(s, 2).ok())
                    .collect();
                rows.chunks_exact(16)
                    .map(|r| r.try_into().unwrap())
                    .collect()
            })
        });
        let Some(rows) = art[group].get(index) else {
            return;
        };
        let unit = (r[2] / 16.).floor().max(1.);
        let (x, y) = (
            r[0] + (r[2] - 16. * unit) / 2.,
            r[1] + (r[3] - 16. * unit) / 2.,
        );
        for (row, bits) in rows.iter().enumerate() {
            let mut col = 0;
            while col < 16 {
                if bits & (1 << (15 - col)) == 0 {
                    col += 1;
                    continue;
                }
                let start = col;
                while col < 16 && bits & (1 << (15 - col)) != 0 {
                    col += 1;
                }
                self.fill(
                    [
                        x + start as f32 * unit,
                        y + row as f32 * unit,
                        (col - start) as f32 * unit,
                        unit,
                    ],
                    color,
                );
            }
        }
    }
}

/// Decode the supplied wheel masks once at atlas construction, at their largest
/// native draw size (232 GUI pixels). Only used tiles are kept, rather than eight
/// mostly empty 2048x2560 atlases in GPU memory.
pub(crate) fn images() -> crate::Result<Vec<(String, u32, u32, Vec<u8>)>> {
    let mut images = Vec::new();
    for (name, bytes) in [
        (
            "cubeon/client-logo",
            include_bytes!("../../../../../assets/icon_128.png").as_slice(),
        ),
        (
            "cubeon/ui/rounded",
            include_bytes!(
                "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/rounded.png"
            )
            .as_slice(),
        ),
        (
            "cubeon/ui/emotes",
            include_bytes!(
                "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/icons.png"
            )
            .as_slice(),
        ),
    ] {
        let (w, h, rgba) = crate::hud::decode_bytes(bytes)?;
        images.push((name.into(), w, h, rgba));
    }
    let wheels: [&[u8]; 8] = [
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-1.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-2.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-3.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-4.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-5.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-6.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-7.png"
        ),
        include_bytes!(
            "../../../../../mod/src/main/resources/assets/cubeon-client/textures/ui/wheel-8.png"
        ),
    ];
    for (i, bytes) in wheels.iter().enumerate() {
        let (w, _, rgba) = crate::hud::decode_bytes(bytes)?;
        for tile in 0..2 * (i + 1) + 2 {
            let mut pixels = vec![0u8; 256 * 256 * 4];
            for y in 0..256 {
                for x in 0..256 {
                    for channel in 0..4 {
                        let source =
                            ((tile / 4 * 512 + y * 2) * w as usize + tile % 4 * 512 + x * 2) * 4
                                + channel;
                        let sum = rgba[source] as u32
                            + rgba[source + 4] as u32
                            + rgba[source + w as usize * 4] as u32
                            + rgba[source + w as usize * 4 + 4] as u32;
                        pixels[(y * 256 + x) * 4 + channel] = ((sum + 2) / 4) as u8;
                    }
                }
            }
            images.push((format!("cubeon/wheel/{}/{tile}", i + 1), 256, 256, pixels));
        }
    }
    Ok(images)
}
