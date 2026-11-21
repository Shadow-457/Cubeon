//! One bounded launcher worker; the launcher owns accounts, encryption and delivery.
use serde_json::{Value, json};
use std::{
    collections::VecDeque,
    io::Read,
    path::PathBuf,
    sync::{
        Arc, Mutex,
        atomic::{AtomicBool, AtomicU64, Ordering},
        mpsc,
    },
    time::{Duration, Instant},
};

#[derive(Clone, Debug)]
pub struct ActionResult {
    pub id: u64,
    pub ok: bool,
    pub error: String,
    pub value: Value,
    pub generation: u64,
}
#[derive(Clone, Default)]
pub struct Snapshot {
    pub friends: Value,
    pub chat: Value,
    pub players: Value,
    pub emotes: Value,
    pub events: VecDeque<Value>,
    pub results: VecDeque<ActionResult>,
    pub up: bool,
    pub error: String,
    pub generation: u64,
    pub account: String,
    pub memory_mib: Option<u64>,
    session: String,
}
enum Command {
    Context(String),
    Chat(String),
    Metrics(bool),
    Action {
        id: u64,
        path: String,
        body: Value,
        session: String,
        account: String,
        generation: u64,
    },
}
pub struct Bridge {
    send: mpsc::SyncSender<Command>,
    shared: Arc<Mutex<Arc<Snapshot>>>,
    previous: Arc<Snapshot>,
    serial: AtomicU64,
    sending: Arc<AtomicBool>,
    room: String,
    peer: String,
    metrics: bool,
}
impl Default for Bridge {
    fn default() -> Self {
        Self::new()
    }
}
impl Bridge {
    pub fn new() -> Self {
        let path = std::env::var_os("CUBEON_BRIDGE_FILE")
            .map(PathBuf::from)
            .unwrap_or_else(|| {
                PathBuf::from(
                    std::env::var_os("HOME")
                        .or_else(|| std::env::var_os("USERPROFILE"))
                        .unwrap_or_default(),
                )
                .join(".cubeon_launcher/local_api.json")
            });
        let (send, recv) = mpsc::sync_channel(16);
        let shared = Arc::new(Mutex::new(Arc::new(Snapshot::default())));
        let sending = Arc::new(AtomicBool::new(false));
        if std::env::var("CUBEON_CLIENT_ENABLED").as_deref() != Ok("0") {
            let (output, busy) = (shared.clone(), sending.clone());
            let _ = std::thread::Builder::new()
                .name("Cubeon bridge".into())
                .spawn(move || run(path, recv, output, busy));
        }
        Self {
            send,
            shared,
            previous: Arc::new(Snapshot::default()),
            serial: AtomicU64::new(1),
            sending,
            room: String::new(),
            peer: String::new(),
            metrics: false,
        }
    }
    pub fn snapshot(&mut self) -> &Snapshot {
        if let Ok(s)=self.shared.try_lock() {self.previous=s.clone();} &self.previous
    }
    pub fn snapshot_arc(&mut self) -> Arc<Snapshot> {
        self.snapshot();
        self.previous.clone()
    }
    pub fn context(&mut self, room: String) {
        if self.room != room && self.send.try_send(Command::Context(room.clone())).is_ok() {
            self.room = room;
        }
    }
    pub fn chat(&mut self, peer: String) {
        if self.peer != peer && self.send.try_send(Command::Chat(peer.clone())).is_ok() {
            self.peer = peer;
        }
    }
    pub fn sending(&self) -> bool {
        self.sending.load(Ordering::Relaxed)
    }
    pub fn metrics(&mut self, on: bool) {
        if self.metrics != on && self.send.try_send(Command::Metrics(on)).is_ok() {
            self.metrics = on;
        }
    }
    /// The ID identifies the exact result. Queue acceptance never means delivery.
    pub fn submit(&self, path: &str, body: Value) -> Option<u64> {
        if self.previous.session.is_empty() {
            return None;
        }
        let dm = path == "/dm";
        if dm
            && self
                .sending
                .compare_exchange(false, true, Ordering::AcqRel, Ordering::Relaxed)
                .is_err()
        {
            return None;
        }
        let id = self.serial.fetch_add(1, Ordering::Relaxed);
        if self
            .send
            .try_send(Command::Action {
                id,
                path: path.into(),
                body,
                session: self.previous.session.clone(),
                account: self.previous.account.clone(),
                generation: self.previous.generation,
            })
            .is_err()
        {
            if dm {
                self.sending.store(false, Ordering::Release);
            }
            return None;
        }
        Some(id)
    }
    pub fn action(&self, path: &str, body: Value) -> bool {
        self.submit(path, body).is_some()
    }
}
fn credentials(path:&PathBuf) -> Option<(u16,String)> {
    let mut data=Vec::new();std::fs::File::open(path).ok()?.take(4097).read_to_end(&mut data).ok()?;
    if data.len()>4096 {return None;}
    let value:Value=serde_json::from_slice(&data).ok()?;
    let port=value["port"].as_u64().filter(|p|*p>0 && *p<=65535)? as u16;
    let token=value["token"].as_str()?;
    if !(16..=256).contains(&token.len())||!token.bytes().all(|b|b.is_ascii_alphanumeric()||b==b'_'||b==b'-') {return None;}
    Some((port,token.into()))
}
fn session(c: &Option<(u16, String)>) -> String {
    c.as_ref()
        .map(|(port, token)| format!("{port}:{token}"))
        .unwrap_or_default()
}
fn request(
    agent: &ureq::Agent,
    c: &(u16, String),
    path: &str,
    body: Option<Value>,
) -> Result<Value, String> {
    // No arbitrary destinations or redirects carrying the capability header.
    if !path.starts_with('/') || path.starts_with("//") || path.contains(['\r', '\n']) {
        return Err("Invalid Cubeon action".into());
    }
    let url = format!("http://127.0.0.1:{}{path}", c.0);
    let request = if body.is_some() {
        agent.post(&url)
    } else {
        agent.get(&url)
    }
    .set("X-Cubeon-Token", &c.1);
    let result = if let Some(body) = body {
        request
            .set("Content-Type", "application/json")
            .send_string(&body.to_string())
    } else {
        request.call()
    };
    let response = match result {
        Ok(r) => r,
        Err(ureq::Error::Status(_, r)) => r,
        Err(_) => return Err("Cubeon launcher not found".into()),
    };
    let code = response.status();
    let mut bytes = Vec::new();
    response
        .into_reader()
        .take(1_000_001)
        .read_to_end(&mut bytes)
        .map_err(|_| "Cubeon response failed")?;
    if bytes.len() > 1_000_000 {
        return Err("Cubeon response too large".into());
    }
    let value: Value = serde_json::from_slice(&bytes).map_err(|_| "Cubeon response is invalid")?;
    if code >= 300 || value["ok"].as_bool() == Some(false) {
        return Err(value["error"]
            .as_str()
            .unwrap_or("Cubeon action failed")
            .into());
    }
    Ok(value)
}
pub fn query_name(name: &str) -> String {
    let mut result = String::new();
    for b in name.bytes() {
        if b.is_ascii_alphanumeric() || b"-._~".contains(&b) {
            result.push(b as char);
        } else {
            result.push_str(&format!("%{b:02X}"));
        }
    }
    result
}
fn merge_chat(
    state: &mut Value,
    next: Value,
    peer: &str,
    account: &str,
    cursor: &mut i64,
) -> Result<(), String> {
    if next["friend"].as_str().is_some_and(|v| v != peer)
        || next["you"]
            .as_str()
            .is_some_and(|v| !v.is_empty() && v != account)
    {
        return Err("Cubeon account changed; reopen chat".into());
    }
    let mut messages = state["messages"].as_array().cloned().unwrap_or_default();
    for message in next["messages"].as_array().into_iter().flatten().take(200) {
        let Some(seq) = message["seq"].as_i64().filter(|s| *s >= 0) else {
            continue;
        };
        if !messages.iter().any(|m| m["seq"].as_i64() == Some(seq)) {
            messages.push(message.clone());
        }
        *cursor = (*cursor).max(seq);
    }
    messages.sort_by_key(|v| v["seq"].as_i64().unwrap_or(0));
    if messages.len() > 200 {
        messages.drain(..messages.len() - 200);
    }
    *cursor = (*cursor).max(next["cursor"].as_i64().unwrap_or(0));
    *state = json!({"friend":peer, "you":account, "messages":messages, "cursor":*cursor, "loading":false});
    Ok(())
}
fn publish(output: &Mutex<Arc<Snapshot>>, state: &Snapshot) {
    *output.lock().unwrap_or_else(|p| p.into_inner()) = Arc::new(state.clone());
}
fn rotate(state: &mut Snapshot, next: String, account: String) {
    let results = std::mem::take(&mut state.results);
    *state = Snapshot {
        session: next,
        account,
        generation: state.generation.wrapping_add(1),
        results,
        ..Default::default()
    };
}
fn run(
    path: PathBuf,
    recv: mpsc::Receiver<Command>,
    output: Arc<Mutex<Arc<Snapshot>>>,
    sending: Arc<AtomicBool>,
) {
    let agent = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_millis(900))
        .timeout(Duration::from_secs(5))
        .redirects(0)
        .build();
    let actions = ureq::AgentBuilder::new()
        .timeout_connect(Duration::from_millis(900))
        .timeout(Duration::from_secs(30))
        .redirects(0)
        .build();
    let mut state = Snapshot::default();
    let (mut room, mut sent_room, mut peer) = (String::new(), String::new(), String::new());
    let ago = Instant::now() - Duration::from_secs(30);
    let (mut context_at, mut roster_at, mut chat_at, mut events_at, mut emotes_at) =
        (ago, ago, ago, ago, ago);
    let (mut chat_cursor, mut event_cursor, mut misses) = (-1i64, -1i64, 0u32);
    let (mut metrics, mut metrics_at) = (false, ago);
    loop {
        let delay = Duration::from_millis(if room.is_empty() { 750 } else { 250 });
        let first = match recv.recv_timeout(delay) {
            Ok(c) => Some(c),
            Err(mpsc::RecvTimeoutError::Timeout) => None,
            Err(_) => break,
        };
        let c = credentials(&path);
        let next_session = session(&c);
        if state.session != next_session {
            rotate(&mut state, next_session.clone(), String::new());
            sent_room.clear();
            chat_cursor = -1;
            event_cursor = -1;
            roster_at = ago;
        }
        let mut commands: Vec<_> = first.into_iter().collect();
        commands.extend(recv.try_iter().take(16));
        // Check the account immediately before every DM, even with an unchanged token.
        let check_account = commands
            .iter()
            .any(|c| matches!(c, Command::Action { path, .. } if path == "/dm"));
        if let Some(c) = &c
            && (roster_at.elapsed() >= Duration::from_secs(6) || check_account)
        {
            roster_at = Instant::now();
            match request(&agent, c, "/friends", None) {
                Ok(value) => {
                    let account = value["you"].as_str().unwrap_or("").to_owned();
                    if state.account != account {
                        rotate(&mut state, next_session.clone(), account);
                        chat_cursor = -1;
                        event_cursor = -1;
                        sent_room.clear();
                    }
                    state.friends = value;
                    state.up = true;
                    if misses > 0 {
                        state.error.clear();
                    }
                    misses = 0;
                }
                Err(e) => {
                    misses += 1;
                    if misses >= 3 {
                        state.up = false;
                    }
                    state.error = e;
                }
            }
            if let Ok(value) = request(&agent, c, "/players", None) {
                state.players = value;
            }
        }
        for command in commands {
            match command {
                Command::Context(next) => {
                    room = next;
                    state.emotes = Value::Null;
                    emotes_at = ago;
                }
                Command::Chat(next) => {
                    if let Some(c) = &c
                        && !peer.is_empty()
                    {
                        let _ = request(&agent, c, "/chatclose", Some(json!({"name":peer})));
                    }
                    peer = next;
                    chat_cursor = -1;
                    chat_at = ago;
                    state.chat = json!({"friend":peer, "you":state.account, "messages":[], "loading":!peer.is_empty()});
                }
                Command::Metrics(on) => {
                    metrics = on;
                    if !on {
                        state.memory_mib = None;
                    }
                    metrics_at = ago;
                }
                Command::Action {
                    id,
                    path: route,
                    body,
                    session: captured,
                    account,
                    generation,
                } => {
                    let result = if captured.is_empty()
                        || captured != next_session
                        || generation != state.generation
                        || account != state.account
                    {
                        Err("Cubeon account changed; your draft has been kept".into())
                    } else if route == "/dm" && (!state.up || misses > 0) {
                        Err("Cannot confirm the Cubeon account; your draft has been kept".into())
                    } else if let Some(c) = &c {
                        request(&actions, c, &route, Some(body))
                    } else {
                        Err("Cubeon launcher not found".into())
                    };
                    let result = if captured != session(&credentials(&path)) {
                        Err("Cubeon session changed; your draft has been kept".into())
                    } else {
                        result
                    };
                    let (ok, value, error) = match result {
                        Ok(v) => (true, v, String::new()),
                        Err(e) => (false, Value::Null, e),
                    };
                    state.error = error.clone();
                    state.results.push_back(ActionResult {
                        id,
                        ok,
                        error,
                        value,
                        generation,
                    });
                    while state.results.len() > 32 {
                        state.results.pop_front();
                    }
                    if route == "/dm" {
                        sending.store(false, Ordering::Release);
                        chat_at = ago;
                    }
                    roster_at = ago;
                    publish(&output, &state);
                }
            }
        }
        if let Some(c) = &c {
            if room != sent_room
                || (!room.is_empty() && context_at.elapsed() >= Duration::from_secs(20))
            {
                if request(&agent, c, "/emotecontext", Some(json!({"room":room}))).is_ok() {
                    sent_room.clone_from(&room);
                    context_at = Instant::now();
                }
            }
            if !room.is_empty() && emotes_at.elapsed() >= Duration::from_millis(250) {
                emotes_at = Instant::now();
                if let Ok(value) = request(&agent, c, "/emotes", None)
                    && value["room"].as_str() == Some(&room)
                {
                    state.emotes = value;
                }
            }
            if !peer.is_empty() && chat_at.elapsed() >= Duration::from_millis(750) {
                chat_at = Instant::now();
                match request(
                    &agent,
                    c,
                    &format!("/chat?friend={}&after={chat_cursor}", query_name(&peer)),
                    None,
                ) {
                    Ok(next) => {
                        if let Err(e) = merge_chat(
                            &mut state.chat,
                            next,
                            &peer,
                            &state.account,
                            &mut chat_cursor,
                        ) {
                            state.chat = Value::Null;
                            state.error = e;
                        }
                    }
                    Err(e) => state.error = e,
                }
            }
            if events_at.elapsed() >= Duration::from_millis(750) {
                events_at = Instant::now();
                if let Ok(value) =
                    request(&agent, c, &format!("/events?since={event_cursor}"), None)
                {
                    if event_cursor >= 0 {
                        for event in value["events"].as_array().into_iter().flatten().take(6) {
                            state.events.push_back(event.clone());
                        }
                        while state.events.len() > 6 {
                            state.events.pop_front();
                        }
                    }
                    event_cursor = value["cursor"].as_i64().unwrap_or(event_cursor.max(0));
                }
            }
        } else {
            state.up = false;
        }
        if metrics && metrics_at.elapsed() >= Duration::from_secs(1) {
            metrics_at = Instant::now();
            state.memory_mib = cubeon_bench::rss_bytes(std::process::id()).map(|v| v >> 20);
        }
        publish(&output, &state);
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test]
    fn names_stay_query_values() {
        assert_eq!(query_name("A&B/"), "A%26B%2F");
    }
    #[test]
    fn chat_merges_sequences_and_caps_history() {
        let (mut state, mut cursor) = (Value::Null, -1);
        for seq in 0..210 {
            merge_chat(
                &mut state,
                json!({"messages":[{"seq":seq,"text":"hello"}]}),
                "Peer",
                "Me",
                &mut cursor,
            )
            .unwrap();
        }
        merge_chat(
            &mut state,
            json!({"messages":[{"seq":209,"text":"duplicate"}]}),
            "Peer",
            "Me",
            &mut cursor,
        )
        .unwrap();
        assert_eq!(state["messages"].as_array().unwrap().len(), 200);
        assert_eq!(state["messages"][0]["seq"], 10);
        assert_eq!(cursor, 209);
        assert!(
            merge_chat(
                &mut state,
                json!({"you":"Other"}),
                "Peer",
                "Me",
                &mut cursor
            )
            .is_err()
        );
    }
}
