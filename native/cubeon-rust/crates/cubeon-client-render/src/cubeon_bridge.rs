//! One bounded loopback worker. The launcher owns accounts, encryption and publication.
use std::{io::Read, path::PathBuf, sync::{Arc,Mutex,mpsc}, time::{Duration,Instant}};
use serde_json::{Value,json};

#[derive(Clone,Default)]
pub struct Snapshot {
    pub friends:Value, pub chat:Value, pub players:Value, pub emotes:Value,
    pub up:bool, pub error:String,
    session:String,
}
enum Command {
    Context(String), Chat(String), Action {path:String,body:Value,session:String},
}
pub struct Bridge {
    send:mpsc::SyncSender<Command>, shared:Arc<Mutex<Snapshot>>, previous:Snapshot,
    room:String,peer:String,
}
impl Bridge {
    pub fn new() -> Self {
        let path=std::env::var_os("CUBEON_BRIDGE_FILE").map(PathBuf::from).unwrap_or_else(|| {
            PathBuf::from(std::env::var_os("HOME").or_else(||std::env::var_os("USERPROFILE")).unwrap_or_default()).join(".cubeon_launcher/local_api.json")
        });
        let (send,recv)=mpsc::sync_channel(16); let shared=Arc::new(Mutex::new(Snapshot::default()));let output=shared.clone();
        if std::env::var("CUBEON_CLIENT_ENABLED").as_deref()!=Ok("0") {
            std::thread::Builder::new().name("Cubeon bridge".into()).spawn(move||run(path,recv,output)).ok();
        }
        Self {send,shared,previous:Snapshot::default(),room:String::new(),peer:String::new()}
    }
    pub fn snapshot(&mut self) -> &Snapshot {
        if let Ok(s)=self.shared.try_lock() {self.previous=s.clone();} &self.previous
    }
    pub fn context(&mut self,room:String) {
        if self.room!=room && self.send.try_send(Command::Context(room.clone())).is_ok() {self.room=room;}
    }
    pub fn chat(&mut self,peer:String) {
        if self.peer!=peer && self.send.try_send(Command::Chat(peer.clone())).is_ok() {self.peer=peer;}
    }
    pub fn action(&self,path:&str,body:Value) -> bool {
        self.send.try_send(Command::Action{path:path.into(),body,session:self.previous.session.clone()}).is_ok()
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
fn request(agent:&ureq::Agent,credentials:&(u16,String),path:&str,body:Option<Value>) -> Result<Value,String> {
    // No arbitrary destinations and no redirects carrying the capability header.
    if !path.starts_with('/') || path.contains(['\r','\n']) {return Err("Invalid Cubeon action".into());}
    let url=format!("http://127.0.0.1:{}{}",credentials.0,path);
    let request=if body.is_some() {agent.post(&url)} else {agent.get(&url)}.set("X-Cubeon-Token",&credentials.1);
    let result=if let Some(body)=body {request.set("Content-Type","application/json").send_string(&body.to_string())} else {request.call()};
    let response=match result {Ok(r)=>r,Err(ureq::Error::Status(_,r))=>r,Err(_)=>return Err("Cubeon launcher not found".into())};
    let code=response.status(); let mut bytes=Vec::new();
    response.into_reader().take(1_000_001).read_to_end(&mut bytes).map_err(|_|"Cubeon response failed")?;
    if bytes.len()>1_000_000 {return Err("Cubeon response too large".into());}
    let value:Value=serde_json::from_slice(&bytes).map_err(|_|"Cubeon response is invalid")?;
    if code>=400 {return Err(value["error"].as_str().unwrap_or("Cubeon action failed").into());} Ok(value)
}
fn query_name(name:&str) -> String {
    let mut result=String::new();for b in name.bytes() {
        if b.is_ascii_alphanumeric()||b"-._~".contains(&b) {result.push(b as char);} else {result.push_str(&format!("%{b:02X}"));}
    } result
}
fn run(path:PathBuf,recv:mpsc::Receiver<Command>,output:Arc<Mutex<Snapshot>>) {
    let agent=ureq::AgentBuilder::new().timeout_connect(Duration::from_millis(900)).timeout(Duration::from_secs(5)).redirects(0).build();
    let actions=ureq::AgentBuilder::new().timeout_connect(Duration::from_millis(900)).timeout(Duration::from_secs(30)).redirects(0).build();
    let mut state=Snapshot::default();let mut room=String::new();let mut sent_room=String::new();let mut peer=String::new();
    let mut context_at=Instant::now()-Duration::from_secs(30);let mut roster_at=context_at;let mut misses=0;
    loop {
        let first=match recv.recv_timeout(Duration::from_millis(750)) {Ok(c)=>Some(c),Err(mpsc::RecvTimeoutError::Timeout)=>None,Err(_)=>break};
        let credentials=credentials(&path);
        let next_session=credentials.as_ref().map(|c|c.1.clone()).unwrap_or_default();
        if state.session!=next_session {state=Snapshot{session:next_session.clone(),..Default::default()};sent_room.clear();roster_at=Instant::now()-Duration::from_secs(10);}
        let mut commands=Vec::new();if let Some(first)=first {commands.push(first);} commands.extend(recv.try_iter().take(16));
        for command in commands {
            match command {
                Command::Context(next)=>{room=next;state.emotes=Value::Null;}
                Command::Chat(next)=>{
                    if let Some(c)=&credentials && !peer.is_empty() {let _=request(&agent,c,"/chatclose",Some(json!({"name":peer})));}
                    peer=next;state.chat=Value::Null;
                }
                Command::Action{path,body,session}=> {
                    state.error=if session.is_empty()||session!=next_session {"Cubeon session changed; try again".into()}
                    else if let Some(c)=&credentials {
                        match request(&actions,c,&path,Some(body)) {
                            Ok(value)=>if value["ok"].as_bool()==Some(false) {value["error"].as_str().unwrap_or("Action failed").into()} else {String::new()},Err(e)=>e
                        }
                    } else {"Cubeon launcher not found".into()};
                    roster_at=Instant::now()-Duration::from_secs(10);
                }
            }
        }
        if let Some(c)=&credentials {
            if roster_at.elapsed()>=Duration::from_secs(6) {
                roster_at=Instant::now();
                match request(&agent,c,"/friends",None) {
                    Ok(value)=>{state.friends=value;state.up=true;misses=0;},Err(e)=>{misses+=1;if misses>=3 {state.up=false;state.error=e;}}
                }
                if let Ok(value)=request(&agent,c,"/players",None) {state.players=value;}
            }
            if room!=sent_room || (!room.is_empty()&&context_at.elapsed()>=Duration::from_secs(20)) {
                if request(&agent,c,"/emotecontext",Some(json!({"room":room}))).is_ok() {sent_room=room.clone();context_at=Instant::now();}
            }
            if !room.is_empty() && let Ok(value)=request(&agent,c,"/emotes",None) {
                if value["room"].as_str()==Some(&room) {state.emotes=value;}
            }
            if !peer.is_empty() && let Ok(value)=request(&agent,c,&format!("/chat?friend={}&after=0",query_name(&peer)),None) {state.chat=value;}
        } else {state.up=false;}
        *output.lock().unwrap_or_else(|p|p.into_inner())=state.clone();
    }
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn names_stay_query_values() {assert_eq!(query_name("A&B/"),"A%26B%2F");}
}
