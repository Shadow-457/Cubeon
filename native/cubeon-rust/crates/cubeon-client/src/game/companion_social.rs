//! Friends, account-bound drafts and relay-confirmed chat on the existing bridge.
use super::{
    Game,
    companion::{Action, Bubble, PendingSend},
};
use cubeon_client::{clipboard::Clipboard, cubeon_bridge::Snapshot, hud::HudBatch};
use cubeon_client_render::cubeon_ui::{self as art, Canvas};
use serde_json::{Value, json};

fn name(friend: &Value) -> &str {
    friend["minecraft_username"]
        .as_str()
        .filter(|n| !n.is_empty())
        .or_else(|| friend["display_name"].as_str().filter(|n| !n.is_empty()))
        .or_else(|| friend["uid"].as_str())
        .unwrap_or("Player")
}
fn account(friend: &Value) -> &str {
    friend["name"].as_str().unwrap_or("")
}
fn friends(snapshot: &Snapshot) -> Vec<Value> {
    snapshot.friends["friends"]
        .as_array()
        .cloned()
        .unwrap_or_default()
}
fn incoming(snapshot: &Snapshot) -> Vec<Value> {
    let details = snapshot.friends["requests_in_details"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if !details.is_empty() {
        details
    } else {
        snapshot.friends["requests_in"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|v| json!({"name":v,"uid":v}))
            .collect()
    }
}
fn outgoing(snapshot: &Snapshot) -> Vec<Value> {
    let details = snapshot.friends["requests_out_details"]
        .as_array()
        .cloned()
        .unwrap_or_default();
    if !details.is_empty() {
        details
    } else {
        snapshot.friends["requests_out"]
            .as_array()
            .into_iter()
            .flatten()
            .map(|v| json!({"name":v,"uid":v}))
            .collect()
    }
}
impl Game<'_> {
    pub(super) fn cubeon_social_frame(&mut self, snapshot: &Snapshot) {
        let c = &mut self.companion;
        if c.generation != snapshot.generation {
            c.remember_draft();
            c.account = snapshot.account.clone();
            c.generation = snapshot.generation;
            c.remove_confirm = false;
            c.peer.clear();
            c.composer.set_value("");
            c.bridge.chat(String::new());
            c.notices.clear();
            c.event_seen = -1;
        }
        if let Some(pending) = &c.pending
            && let Some(result) = snapshot.results.iter().find(|r| r.id == pending.id)
        {
            let pending = c.pending.take().unwrap();
            if result.ok && pending.generation == c.generation && pending.account == c.account {
                let key = (pending.account.clone(), pending.peer.clone());
                if c.drafts
                    .get(&key)
                    .is_some_and(|draft| draft.trim() == pending.text)
                {
                    c.drafts.remove(&key);
                }
                if c.peer == pending.peer && c.composer.value.trim() == pending.text {
                    c.composer.set_value("");
                }
                c.local_error.clear();
            } else {
                c.local_error = if result.error.is_empty() {
                    "Account changed; your draft has been kept.".into()
                } else {
                    result.error.clone()
                };
                c.notice(c.local_error.clone(), true);
            }
        }
        if let Some((id, _, _, _)) = c.social_pending.as_ref()
            && let Some(result) = snapshot.results.iter().find(|r| r.id == *id)
        {
            let (_, operation, target, generation) = c.social_pending.take().unwrap();
            if result.ok && generation == c.generation {
                c.local_error.clear();
                c.notice(
                    match operation.as_str() {
                        "/add" => "Friend request sent",
                        "/accept" => "Friend request accepted",
                        "/decline" => "Friend request declined",
                        _ => "Friend removed or request cancelled",
                    }
                    .into(),
                    false,
                );
                if operation == "/add" {
                    c.add.set_value("");
                }
                if operation == "/remove" && c.peer == target {
                    c.remember_draft();
                    c.peer.clear();
                    c.composer.set_value("");
                    c.bridge.chat(String::new());
                }
                c.remove_confirm = false;
            } else {
                c.local_error = if result.error.is_empty() {
                    "Account changed; action not confirmed.".into()
                } else {
                    result.error.clone()
                };
                c.notice(c.local_error.clone(), true);
            }
        }
        for event in &snapshot.events {
            let seq = event["seq"].as_i64().unwrap_or(-1);
            if seq > c.event_seen {
                c.event_seen = seq;
                c.notice(
                    event["text"].as_str().unwrap_or("").into(),
                    event["error"].as_bool().unwrap_or(false),
                );
            }
        }
        c.notices.retain(|n| n.born.elapsed().as_secs_f32() < 5.);
        if c.open && matches!(c.tab, 2 | 3) && !c.manage_friends && !c.peer.is_empty() {
            c.bridge.chat(c.peer.clone());
        }
    }
    pub(super) fn cubeon_input_send(&mut self) {
        let c = &mut self.companion;
        if c.pending.is_some()
            || c.bridge.sending()
            || c.peer.is_empty()
            || c.composer.value.trim().is_empty()
        {
            return;
        }
        c.remember_draft();
        let snapshot = c.bridge.snapshot_arc();
        if !snapshot.up
            || snapshot.friends["connected"].as_bool() == Some(false)
            || snapshot.generation != c.generation
        {
            c.local_error = "Connect your Cubeon account in the launcher to send.".into();
            return;
        }
        let text = c.composer.value.trim().to_owned();
        if let Some(id) = c.bridge.submit("/dm", json!({"to":c.peer,"text":text})) {
            c.pending = Some(PendingSend {
                id,
                account: c.account.clone(),
                peer: c.peer.clone(),
                text,
                generation: c.generation,
            });
            c.local_error.clear();
        } else {
            c.local_error = "A message is already sending; your draft has been kept.".into();
        }
    }
    fn cubeon_friend_command(&mut self, path: &str, target: String) {
        let c = &mut self.companion;
        if c.social_pending.is_some() {
            return;
        }
        if let Some(id) = c.bridge.submit(path, json!({"name":target})) {
            c.social_pending = Some((id, path.into(), target, c.generation));
            c.local_error = "Confirming friend action…".into();
        } else {
            c.local_error = "Connect your Cubeon account in the launcher first.".into();
        }
    }
    pub(super) fn cubeon_add_friend(&mut self) {
        let value = self.companion.add.value.trim().to_owned();
        if !value.is_empty() {
            self.cubeon_friend_command("/add", value);
        }
    }
    pub(super) fn cubeon_friends_screen(&mut self, batch: &mut HudBatch) {
        let pw = (batch.width - 32.)
            .min(660.)
            .min((batch.width * 0.84).max(288.));
        let ph = (batch.height - 24.)
            .min(380.)
            .min((batch.height * 0.84).max(216.));
        let (x, y) = ((batch.width - pw) / 2., (batch.height - ph) / 2.);
        let rail = (pw * 0.28).clamp(88., 180.);
        let left = x + rail + 16.;
        let body = pw - rail - 32.;
        let cursor = self.cursor;
        let c = &mut self.companion;
        let snapshot = c.bridge.snapshot_arc();
        let list = friends(&snapshot);
        let p = c.palette;
        let fade = if c.boolean("menuAnimations", true) {
            (c.opened.elapsed().as_secs_f32() / 0.16).min(1.)
        } else {
            1.
        };
        let mut ui = Canvas {
            batch,
            atlas: &self.gui.atlas,
            palette: p,
            fade,
        };
        ui.pixel([x, y, pw, ph], p.surface(), p.rim());
        ui.mark(x + 12., y + 16.);
        ui.text(
            &art::fit(ui.atlas, "Friends", rail - 46.),
            x + 40.,
            y + 21.,
            p.text(),
        );
        c.button(
            &mut ui,
            cursor,
            Action::Back,
            [x + pw - 36., y + 12., 24., 24.],
            "×",
            true,
            false,
        );
        c.button(
            &mut ui,
            cursor,
            Action::FriendsMode(!c.manage_friends),
            [x + 8., y + 42., rail - 12., 18.],
            if c.manage_friends {
                "Back to chats"
            } else {
                "Manage friends"
            },
            true,
            c.manage_friends,
        );
        ui.fill([x + rail, y + 12., 1., ph - 24.], p.border());
        let selected = list.iter().find(|f| account(f) == c.peer);
        c.friend_rail = [x, y, rail, ph];
        let connected = c.social_pending.is_none()
            && snapshot.up
            && snapshot.friends["connected"].as_bool() != Some(false);
        let heading = if c.manage_friends {
            "Friend requests"
        } else {
            selected.map(name).unwrap_or("Cubeon chat")
        };
        ui.text(
            &art::fit(ui.atlas, heading, body - 30.),
            left,
            y + 18.,
            p.text(),
        );
        let status = if connected {
            if selected.is_some_and(|f| f["online"].as_bool() == Some(true)) {
                "Online · synced with launcher"
            } else {
                "Synced with launcher"
            }
        } else {
            snapshot.friends["connection"]["line"]
                .as_str()
                .unwrap_or("Connect in the Cubeon launcher")
        };
        ui.text(
            &art::fit(ui.atlas, status, body - 12.),
            left,
            y + 32.,
            p.dim(),
        );
        ui.fill([left, y + 52., body, 1.], p.border());
        let visible = ((ph - 84.) / 36.).floor().max(1.) as usize;
        c.friend_offset = c.friend_offset.min(list.len().saturating_sub(visible));
        for (i, friend) in list.iter().enumerate().skip(c.friend_offset).take(visible) {
            let top = y + 64. + (i - c.friend_offset) as f32 * 36.;
            let r = [x + 8., top, rail - 12., 32.];
            let active = account(friend) == c.peer;
            ui.pixel(
                r,
                if active {
                    art::mix(p.cards(), p.accent(), 0.3)
                } else if art::contains(cursor, r) {
                    p.cards()
                } else {
                    p.surface()
                },
                if active { p.accent() } else { p.border() },
            );
            avatar(
                &mut ui,
                name(friend),
                [x + 16., top + 6., 20., 20.],
                friend["online"].as_bool() == Some(true),
            );
            ui.text(
                &art::fit(ui.atlas, name(friend), rail - 55.),
                x + 42.,
                top + 5.,
                p.text(),
            );
            let unread = friend["unread"]
                .as_u64()
                .or_else(|| friend["unread_count"].as_u64())
                .unwrap_or(0);
            let line = if unread > 0 {
                format!("{unread} unread")
            } else if let Some(version) = friend["version"].as_str().filter(|v| !v.is_empty()) {
                format!("Playing {version}")
            } else {
                if friend["online"].as_bool() == Some(true) {
                    "Online"
                } else {
                    "Offline"
                }
                .into()
            };
            ui.text(
                &art::fit(ui.atlas, &line, rail - 52.),
                x + 42.,
                top + 18.,
                p.faint(),
            );
            c.register(Action::Friend(i), r, name(friend), true);
        }
        if list.is_empty() {
            ui.text("No friends yet", x + 12., y + 74., p.dim());
        }
        if list.len() > visible {
            c.button(
                &mut ui,
                cursor,
                Action::FriendPage(-1),
                [x + 8., y + ph - 24., (rail - 16.) / 2., 16.],
                "↑",
                c.friend_offset > 0,
                false,
            );
            c.button(
                &mut ui,
                cursor,
                Action::FriendPage(1),
                [x + rail / 2., y + ph - 24., (rail - 16.) / 2., 16.],
                "↓",
                c.friend_offset + visible < list.len(),
                false,
            );
        }
        if c.manage_friends {
            let input = [left, y + 64., (body - 66.).max(20.), 24.];
            ui.pixel(input, p.cards(), p.rim());
            c.add.x = input[0] + 6.;
            c.add.y = input[1] + 8.;
            c.add.width = input[2] - 12.;
            c.add.height = 9.;
            c.add.text_color = art::native_color(p.text());
            if c.add.value.is_empty() && c.field != Some(2) {
                ui.text("Cubeon ID", input[0] + 6., input[1] + 8., p.faint());
            } else if c.field != Some(2) {
                c.add.draw(ui.batch, ui.atlas, None);
            }
            c.register(Action::Field(2), input, "Cubeon ID", true);
            c.button(
                &mut ui,
                cursor,
                Action::Add,
                [left + body - 60., y + 64., 60., 24.],
                "Add",
                connected,
                false,
            );
            let requests = incoming(&snapshot);
            let outgoing = outgoing(&snapshot);
            let row_count = ((ph - 154.) / 30.).floor().max(1.) as usize;
            let total = requests.len() + outgoing.len();
            c.pages = total.div_ceil(row_count).max(1);
            c.page = c.page.min(c.pages - 1);
            for (row, index) in
                (c.page * row_count..total.min((c.page + 1) * row_count)).enumerate()
            {
                let top = y + 104. + row as f32 * 30.;
                if let Some(friend) = requests.get(index) {
                    ui.text(
                        &art::fit(ui.atlas, name(friend), (body - 124.).max(12.)),
                        left,
                        top + 8.,
                        p.text(),
                    );
                    c.button(
                        &mut ui,
                        cursor,
                        Action::Request(index, true),
                        [left + body - 118., top, 56., 24.],
                        "Accept",
                        connected,
                        true,
                    );
                    c.button(
                        &mut ui,
                        cursor,
                        Action::Request(index, false),
                        [left + body - 58., top, 58., 24.],
                        "Decline",
                        connected,
                        false,
                    );
                } else if let Some(friend) = outgoing.get(index - requests.len()) {
                    ui.text(
                        &art::fit(ui.atlas, &format!("Pending: {}", name(friend)), body - 65.),
                        left,
                        top + 8.,
                        p.dim(),
                    );
                    c.button(
                        &mut ui,
                        cursor,
                        Action::CancelRequest(index - requests.len()),
                        [left + body - 60., top, 60., 24.],
                        "Cancel",
                        connected,
                        false,
                    );
                }
            }
            if total == 0 {
                ui.text("No pending requests", left, y + 111., p.faint());
            }
            if c.pages > 1 {
                c.button(
                    &mut ui,
                    cursor,
                    Action::Page(-1),
                    [left, y + ph - 55., 26., 18.],
                    "‹",
                    c.page > 0,
                    false,
                );
                c.button(
                    &mut ui,
                    cursor,
                    Action::Page(1),
                    [left + body - 26., y + ph - 55., 26., 18.],
                    "›",
                    c.page + 1 < c.pages,
                    false,
                );
            }
            if !c.local_error.is_empty() {
                ui.text(
                    &art::fit(ui.atlas, &c.local_error, body - 68.),
                    left + 32.,
                    y + ph - 49.,
                    p.dim(),
                );
            }
            let uid = snapshot.friends["you_uid"].as_str().unwrap_or("");
            c.button(
                &mut ui,
                cursor,
                Action::CopyId,
                [left, y + ph - 32., body, 22.],
                &format!("Your Cubeon ID: {uid} · Copy"),
                !uid.is_empty(),
                false,
            );
        } else {
            let top = y + 64.;
            let bottom = y + ph - 80.;
            if c.peer.is_empty() {
                ui.text(
                    &art::fit(ui.atlas, "Select a friend to chat", body),
                    left,
                    top + 16.,
                    p.dim(),
                );
                ui.text(
                    &art::fit(ui.atlas, "Add friends by their Cubeon ID.", body),
                    left,
                    top + 32.,
                    p.faint(),
                );
            } else if snapshot.chat["loading"].as_bool() == Some(true) {
                ui.text("Loading messages…", left, top + 12., p.dim());
            } else {
                let messages = if snapshot.chat["friend"].as_str() == Some(&c.peer) {
                    snapshot.chat["messages"]
                        .as_array()
                        .cloned()
                        .unwrap_or_default()
                } else {
                    Vec::new()
                };
                let key = (
                    c.generation,
                    c.peer.clone(),
                    snapshot.chat["cursor"].as_i64().unwrap_or(-1),
                    messages.len(),
                    body.to_bits(),
                    HudBatch::text_width(ui.atlas, "AaW").to_bits(),
                );
                if c.transcript.key.as_ref() != Some(&key) {
                    c.transcript.key = Some(key);
                    c.transcript.bubbles.clear();
                    let mut height = 0.;
                    for message in messages.iter().take(200) {
                        let text = message["text"]
                            .as_str()
                            .unwrap_or("")
                            .replace('\r', " ")
                            .replace('§', " ");
                        let lines =
                            cubeon_client::multiplayer::wrap(&text, (body - 36.).max(1.), ui.atlas);
                        let width = lines
                            .iter()
                            .map(|l| HudBatch::text_width(ui.atlas, l))
                            .fold(12., f32::max)
                            + 20.;
                        let bh = lines.len().max(1) as f32 * 12. + 12.;
                        c.transcript.bubbles.push(Bubble {
                            out: message["direction"].as_str() == Some("out"),
                            lines,
                            width: width.min(body),
                            height: bh,
                            y: height,
                        });
                        height += bh + 8.;
                    }
                    c.transcript_height = (height - 8.).max(0.);
                }
                let viewport = (bottom - top).max(1.);
                c.transcript_scroll = c
                    .transcript_scroll
                    .min((c.transcript_height - viewport).max(0.));
                let offset = (c.transcript_height - viewport).max(0.) - c.transcript_scroll;
                for bubble in &c.transcript.bubbles {
                    let by = top + bubble.y - offset;
                    if by >= bottom || by + bubble.height <= top {
                        continue;
                    }
                    let bx = if bubble.out {
                        left + body - bubble.width
                    } else {
                        left
                    };
                    let start = ui.batch.vertices.len();
                    ui.pixel(
                        [bx, by, bubble.width, bubble.height],
                        if bubble.out { p.selected() } else { p.cards() },
                        if bubble.out { p.rim() } else { p.border() },
                    );
                    for (i, line) in bubble.lines.iter().enumerate() {
                        ui.text(line, bx + 10., by + 8. + i as f32 * 12., p.text());
                    }
                    ui.batch.clip_since(start, left, top, left + body, bottom);
                }
                if messages.is_empty() {
                    ui.text("Say hello", left, top + 12., p.faint());
                }
            }
            let feedback = if !c.local_error.is_empty() {
                c.local_error.as_str()
            } else if c.pending.is_some() {
                "Confirming delivery…"
            } else {
                snapshot.error.as_str()
            };
            for (i, line) in cubeon_client::multiplayer::wrap(feedback, body, ui.atlas)
                .iter()
                .take(2)
                .enumerate()
            {
                ui.text(
                    line,
                    left,
                    y + ph - 76. + i as f32 * 11.,
                    if c.pending.is_some() {
                        p.dim()
                    } else {
                        0xffff9c89
                    },
                );
            }
            let input = [left - 4., y + ph - 44., (body - 36.).max(16.), 28.];
            ui.pixel(input, p.cards(), p.rim());
            c.composer.x = left + 4.;
            c.composer.y = input[1] + 10.;
            c.composer.width = input[2] - 16.;
            c.composer.height = 9.;
            c.composer.text_color = art::native_color(p.text());
            if c.field != Some(1) {
                c.composer.draw(ui.batch, ui.atlas, None);
            }
            c.register(Action::Field(1), input, "Message", !c.peer.is_empty());
            let ready = !c.peer.is_empty()
                && connected
                && c.pending.is_none()
                && !c.bridge.sending()
                && !c.composer.value.trim().is_empty();
            c.button(
                &mut ui,
                cursor,
                Action::Send,
                [x + pw - 44., y + ph - 44., 32., 28.],
                "➤",
                ready,
                true,
            );
            ui.text(
                &art::fit(ui.atlas, "Enter sends · Escape returns", body),
                left,
                y + ph - 11.,
                p.faint(),
            );
            if !c.peer.is_empty() {
                c.button(
                    &mut ui,
                    cursor,
                    if c.remove_confirm {
                        Action::ConfirmRemove
                    } else {
                        Action::Remove
                    },
                    [x + pw - 92., y + 12., 48., 20.],
                    if c.remove_confirm {
                        "Confirm"
                    } else {
                        "Remove"
                    },
                    connected,
                    false,
                );
                if c.remove_confirm {
                    c.button(
                        &mut ui,
                        cursor,
                        Action::Remove,
                        [x + pw - 146., y + 12., 50., 20.],
                        "Cancel",
                        true,
                        false,
                    );
                }
            }
        }
    }
    pub(super) fn cubeon_social_action(&mut self, action: Action) {
        match action {
            Action::Friend(index) => {
                let snapshot = self.companion.bridge.snapshot_arc();
                if let Some(friend) = friends(&snapshot).get(index) {
                    let c = &mut self.companion;
                    c.remember_draft();
                    c.peer = account(friend).into();
                    c.tab = 2;
                    c.manage_friends = false;
                    c.remove_confirm = false;
                    c.transcript_scroll = 0.;
                    c.local_error.clear();
                    c.composer.set_value(
                        c.drafts
                            .get(&(c.account.clone(), c.peer.clone()))
                            .map(String::as_str)
                            .unwrap_or(""),
                    );
                    c.set_field(Some(1));
                    c.bridge.chat(c.peer.clone());
                }
            }
            Action::FriendsMode(manage) => {
                let c = &mut self.companion;
                c.remember_draft();
                c.manage_friends = manage;
                c.page = 0;
                c.set_field(if manage { Some(2) } else { Some(1) });
                c.local_error.clear();
            }
            Action::FriendPage(d) if matches!(self.companion.tab, 2 | 3) => {
                let c = &mut self.companion;
                c.friend_offset = c.friend_offset.saturating_add_signed(d as isize * 3);
            }
            Action::Page(d) => {
                let c = &mut self.companion;
                c.page = c.page.saturating_add_signed(d as isize).min(c.pages - 1);
            }
            Action::Add => self.cubeon_add_friend(),
            Action::Send => self.cubeon_input_send(),
            Action::Request(i, accept) => {
                let snapshot = self.companion.bridge.snapshot_arc();
                if let Some(friend) = incoming(&snapshot).get(i) {
                    self.cubeon_friend_command(
                        if accept { "/accept" } else { "/decline" },
                        account(friend).into(),
                    );
                }
            }
            Action::CancelRequest(i) => {
                let snapshot = self.companion.bridge.snapshot_arc();
                if let Some(friend) = outgoing(&snapshot).get(i) {
                    self.cubeon_friend_command("/remove", account(friend).into());
                }
            }
            Action::Remove => {
                self.companion.remove_confirm = !self.companion.remove_confirm;
            }
            Action::ConfirmRemove => {
                self.cubeon_friend_command("/remove", self.companion.peer.clone());
            }
            Action::CopyId => {
                let snapshot = self.companion.bridge.snapshot_arc();
                let uid = snapshot.friends["you_uid"].as_str().unwrap_or("");
                self.clipboard.set(uid);
                self.companion.notice("Cubeon ID copied".into(), false);
            }
            _ => {}
        }
    }
    pub(super) fn cubeon_notices(&mut self, batch: &mut HudBatch) {
        if !self.companion.enabled {
            return;
        }
        let p = self.companion.palette;
        let w = (batch.width - 16.).min(250.);
        let rows = ((batch.height - 16.) / 46.).floor().clamp(0., 3.) as usize;
        for (i, notice) in self.companion.notices.iter().take(rows).enumerate() {
            let age = notice.born.elapsed().as_secs_f32();
            let fade = (age / 0.18).min((5. - age) / 0.25).clamp(0., 1.);
            let mut ui = Canvas {
                batch,
                atlas: &self.gui.atlas,
                palette: p,
                fade,
            };
            let x = ui.batch.width - w - 8.;
            let y = 8. + i as f32 * 46.;
            ui.panel([x, y, w, 40.], p.surface(), p.rim());
            ui.mark(x + 8., y + 10.);
            ui.text(
                "Cubeon",
                x + 34.,
                y + 6.,
                if notice.error { 0xffff9c89 } else { p.bright() },
            );
            ui.text(
                &art::fit(ui.atlas, &notice.text, w - 42.),
                x + 34.,
                y + 21.,
                p.text(),
            );
        }
    }
}
fn avatar(ui: &mut Canvas<'_>, name: &str, r: [f32; 4], online: bool) {
    let p = ui.palette;
    ui.pixel(r, p.selected(), p.border());
    let initial = name
        .chars()
        .next()
        .unwrap_or('?')
        .to_uppercase()
        .to_string();
    ui.center(
        &initial,
        r[0] + r[2] / 2.,
        r[1] + (r[3] - 9.) / 2.,
        p.text(),
    );
    ui.fill(
        [r[0] + r[2] - 6., r[1] + r[3] - 6., 4., 4.],
        if online { p.accent() } else { p.faint() },
    );
}
