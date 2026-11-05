//! CSL-compatible source order without Java or changes to vanilla signature checks.
//! A bounded worker resolves LocalSkin per slot, then Cubeon's public CustomSkinAPI.
//! The game consumes decoded snapshots; it never reads storage or HTTPS in a frame.
use std::{collections::HashMap, io::Read, path::{Path, PathBuf}, sync::{Arc, Mutex, mpsc}, time::{Duration, Instant}};
use serde::Deserialize;
use sha2::{Digest, Sha256};

const BASE: &str = "https://cubeon-skins.hamza-457-shahbaz.workers.dev";
const MAX_PLAYERS: usize = 128;

#[derive(Clone, Deserialize)]
#[serde(default, rename_all="camelCase")]
pub struct Config {
    pub enabled: bool,
    pub username: String,
    pub local_skin_dir: PathBuf,
    pub local_cape_dir: PathBuf,
    pub local_elytra_dir: PathBuf,
    pub model: String,
    pub public_root: String,
}
impl Default for Config {
    fn default() -> Self {
        Self { enabled:true, username:String::new(), local_skin_dir:PathBuf::from("CustomSkinLoader/LocalSkin/skins"),
            local_cape_dir:PathBuf::from("CustomSkinLoader/LocalSkin/capes"), local_elytra_dir:PathBuf::from("CustomSkinLoader/LocalSkin/elytras"),
            model:"classic".into(), public_root:BASE.into() }
    }
}
#[derive(Clone)]
pub struct Image { pub location:String, pub rgba:Arc<[u8]> }
#[derive(Clone, Default)]
pub struct Appearance { pub skin:Option<Image>, pub cape:Option<Image>, pub elytra:Option<Image>, pub slim:bool }
#[derive(Clone, Default)]
pub struct Snapshot { pub players:HashMap<u128, Appearance> }

pub struct Service {
    send:mpsc::SyncSender<Vec<(u128,String)>>,
    current:Arc<Mutex<Snapshot>>,
    previous:Snapshot,
    next:Instant,
}
impl Service {
    pub fn new(root:PathBuf) -> Self {
        let (send,recv)=mpsc::sync_channel(1);
        let current=Arc::new(Mutex::new(Snapshot::default()));
        let output=current.clone();
        std::thread::Builder::new().name("Cubeon skins".into()).spawn(move || run(root,recv,output)).ok();
        Self { send,current,previous:Snapshot::default(),next:Instant::now() }
    }
    /// Nonblocking and bounded even on a busy server. Local identity is queued first.
    pub fn snapshot(&mut self, names:Vec<(u128,String)>) -> &Snapshot {
        if Instant::now()>=self.next {
            self.next=Instant::now()+Duration::from_millis(500);
            let names=names.into_iter().filter(|(_,n)| valid_name(n)).take(MAX_PLAYERS).collect();
            let _=self.send.try_send(names);
        }
        if let Ok(snapshot)=self.current.try_lock() { self.previous=snapshot.clone(); }
        &self.previous
    }
}
pub fn valid_name(name:&str) -> bool {
    (1..=16).contains(&name.len()) && name.bytes().all(|b| b.is_ascii_alphanumeric()||b==b'_')
}
fn bounded_file(path:&Path, max:u64) -> Option<Vec<u8>> {
    let file=std::fs::File::open(path).ok()?;
    let mut bytes=Vec::new(); file.take(max+1).read_to_end(&mut bytes).ok()?;
    (bytes.len() as u64<=max).then_some(bytes)
}
fn decode(bytes:&[u8], skin:bool) -> Option<Image> {
    // Reject dimension bombs before allowing the PNG decoder to allocate.
    if bytes.len()<24 || &bytes[..8]!=b"\x89PNG\r\n\x1a\n" { return None; }
    let w=u32::from_be_bytes(bytes[16..20].try_into().ok()?);
    let h=u32::from_be_bytes(bytes[20..24].try_into().ok()?);
    if w==0 || h==0 || w>1024 || h>1024 { return None; }
    let (w,h,rgba)=crate::hud::decode_bytes(bytes).ok()?;
    let rgba=if skin { crate::skins::process_legacy_skin(w,h,&rgba) } else { crate::skins::process_cape(w,h,&rgba) }?;
    let digest=format!("{:x}",Sha256::digest(&rgba));
    Some(Image { location:format!("{}/cubeon_{digest}",if skin {"skins"} else {"capes"}),rgba:rgba.into() })
}
fn local(dir:&Path,name:&str,skin:bool) -> Option<Image> {
    if !valid_name(name) { return None; }
    decode(&bounded_file(&dir.join(format!("{name}.png")),1024*1024)?,skin)
}
/// First source wins independently for skin, cape and elytra, like CSL's mix().
pub fn merge(local:Appearance, remote:Appearance) -> Appearance {
    let slim=if local.skin.is_some() {local.slim} else {remote.slim};
    Appearance { skin:local.skin.or(remote.skin),cape:local.cape.or(remote.cape),elytra:local.elytra.or(remote.elytra),slim }
}
struct Entry { appearance:Appearance, expires:Instant }
fn read_json(root:&Path) -> Config {
    bounded_file(&root.join("config/cubeon-native-appearance.json"),65536)
        .and_then(|b|serde_json::from_slice(&b).ok()).unwrap_or_default()
}
fn fetch(agent:&ureq::Agent,url:&str,max:u64) -> Option<Vec<u8>> {
    let response=agent.get(url).call().ok()?;
    if response.status()!=200 {return None;}
    let mut bytes=Vec::new(); response.into_reader().take(max+1).read_to_end(&mut bytes).ok()?;
    (bytes.len() as u64<=max).then_some(bytes)
}
fn texture_url(base:&str, id:&str) -> Option<String> {
    // CustomSkinAPI uses bare content hashes; never accept an arbitrary texture URL.
    ((16..=128).contains(&id.len()) && id.bytes().all(|c|c.is_ascii_hexdigit()))
        .then(||format!("{base}/textures/{id}"))
}
fn remote(agent:&ureq::Agent,base:&str,name:&str) -> Option<Appearance> {
    if !valid_name(name) || !(base.starts_with("https://") || base.starts_with("http://127.0.0.1:")) {return None;}
    let value:serde_json::Value=serde_json::from_slice(&fetch(agent,&format!("{base}/skins/{name}.json"),8192)?).ok()?;
    let textures=value.get("textures")?;
    let image=|key,skin|textures.get(key).and_then(|v|v.as_str()).and_then(|id|texture_url(base,id))
        .and_then(|url|fetch(agent,&url,1024*1024)).and_then(|b|decode(&b,skin));
    let slim=textures.get("slim").is_some();
    Some(Appearance {skin:image(if slim {"slim"} else {"default"},true),cape:image("cape",false),elytra:image("elytra",false),slim})
}
fn run(root:PathBuf, requests:mpsc::Receiver<Vec<(u128,String)>>, output:Arc<Mutex<Snapshot>>) {
    let agent=ureq::AgentBuilder::new().timeout_connect(Duration::from_secs(2)).timeout_read(Duration::from_secs(2))
        .timeout_write(Duration::from_secs(2)).redirects(0).build();
    let mut cache:HashMap<String,Entry>=HashMap::new();
    let mut base=String::new(); let mut retry=Instant::now(); let mut failures=0u32;
    let mut next_request=Instant::now();
    while let Ok(mut names)=requests.recv() {
        while let Ok(next)=requests.try_recv() {names=next;}
        let config=read_json(&root);
        if base!=config.public_root {cache.clear(); base=config.public_root.trim_end_matches('/').to_owned(); failures=0;retry=Instant::now();}
        if !config.enabled { *output.lock().unwrap_or_else(|p|p.into_inner())=Snapshot::default(); continue; }
        cache.retain(|name,_|names.iter().any(|(_,n)|n.eq_ignore_ascii_case(name)));
        let mut snapshot=Snapshot::default();
        for (uuid,name) in names.iter().take(MAX_PLAYERS) {
            let mut locals=Appearance {skin:local(&config.local_skin_dir,name,true),cape:local(&config.local_cape_dir,name,false),
                elytra:local(&config.local_elytra_dir,name,false),slim:config.model=="slim"};
            // Peers' local mirrors can carry their own explicit model sidecar.
            if !name.eq_ignore_ascii_case(&config.username) {locals.slim=false;}
            let key=name.to_ascii_lowercase();
            let now=Instant::now();
            let due=cache.get(&key).is_none_or(|e|now>=e.expires);
            if due && now>=retry && now>=next_request && (locals.skin.is_none()||locals.cape.is_none()||locals.elytra.is_none()) {
                next_request=now+Duration::from_millis(1500);
                let found=remote(&agent,&base,name);
                let ttl=if found.is_some() {failures=0;Duration::from_secs(300)} else {
                    failures=(failures+1).min(5); let delay=Duration::from_secs(30<<failures);retry=Instant::now()+delay;delay
                };
                let previous=cache.remove(&key).map(|e|e.appearance).unwrap_or_default();
                cache.insert(key.clone(),Entry {appearance:found.unwrap_or(previous),expires:Instant::now()+ttl});
            }
            let public=cache.get(&key).map(|e|e.appearance.clone()).unwrap_or_default();
            snapshot.players.insert(*uuid,merge(locals,public));
        }
        *output.lock().unwrap_or_else(|p|p.into_inner())=snapshot;
    }
}

#[cfg(test)] mod tests {
    use super::*;
    fn image(id:&str)->Image { Image{location:id.into(),rgba:Arc::from([0;4])} }
    #[test] fn source_order_is_per_slot() {
        let merged=merge(Appearance{skin:Some(image("local")),slim:true,..Default::default()},
            Appearance{skin:Some(image("public")),cape:Some(image("cape")),..Default::default()});
        assert_eq!(merged.skin.unwrap().location,"local");assert!(merged.slim);assert_eq!(merged.cape.unwrap().location,"cape");
    }
    #[test] fn invalid_names_and_urls_cannot_escape_the_source() {
        for name in ["../Steve","A/B","","longer_than_16_characters"] {assert!(!valid_name(name));}
        assert!(valid_name("Steve_123"));assert!(texture_url(BASE,"../../token").is_none());assert!(texture_url(BASE,"https://example.org").is_none());
    }
    #[test] fn png_bombs_are_rejected() {
        let mut bytes=vec![0;24];bytes[..8].copy_from_slice(b"\x89PNG\r\n\x1a\n");bytes[16..20].copy_from_slice(&100000u32.to_be_bytes());
        assert!(decode(&bytes,true).is_none());
    }
}
