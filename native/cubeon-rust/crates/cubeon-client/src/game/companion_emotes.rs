use super::{Game,Screen};
use cubeon_client::{cubeon_emotes as emotes,hud::{HudBatch,rgba},ui};
use serde_json::{Value,json};
impl Game<'_> {
    pub(super) fn cubeon_emotes_frame(&mut self,value:&Value,eligible:bool) {
        if !self.companion.boolean("showEmotes",true) || self.player.is_none() {emotes::clear();return;}
        if let Some(active)=value["active"].as_array() {
            for event in active.iter().take(128) {
                let uuid=event["uuid"].as_str().unwrap_or("").replace('-',"");
                let Ok(uuid)=u128::from_str_radix(&uuid,16) else{continue;};
                let name=event["username"].as_str().unwrap_or("");let emote=event["emote"].as_str().unwrap_or("");
                let serial=event["serial"].as_i64().unwrap_or(-1);let age=event["age"].as_f64().unwrap_or(f64::NAN) as f32;
                let Some(r)=&self.remote else{continue;};
                if uuid==r.profile() && name==self.options.player_name() {emotes::event(0,emote,serial,age);}
                for player in self.mobs.iter().filter(|m|&*m.kind.id=="minecraft:player") {
                    if self.remote_player_uuid(player.id)==Some(uuid) && self.remote_player_name(player.id)==Some(name) {emotes::event(player.id,emote,serial,age);}
                }
            }
        }
        if emotes::playing(0) && eligible && self.player.as_ref().is_some_and(|p|p.velocity.x*p.velocity.x+p.velocity.z*p.velocity.z>0.0004)
            || emotes::playing(0) && (self.left||self.right||self.keys.contains(&winit::keyboard::KeyCode::Space)||self.riding.is_some()) {
            self.cubeon_play_emote("stop");
        }
    }
    fn cubeon_play_emote(&mut self,name:&str) {
        let Some(uuid)=self.remote.as_ref().map(|r|r.profile()) else{return;};
        self.companion.emote_serial+=1;let serial=self.companion.emote_serial;
        emotes::event(0,name,serial,0.);
        self.companion.bridge.action("/emote",json!({"uuid":format!("{uuid:032x}"),"emote":name,"serial":serial}));
    }
    fn wheel_selection(&self)->Option<usize> {
        let (w,h)=self.gui_size();let dx=self.cursor.0-w/2.;let dy=self.cursor.1-h/2.;
        if dx*dx+dy*dy<225. {return None;}
        let angle=(dx.atan2(-dy)+std::f32::consts::TAU+std::f32::consts::FRAC_PI_4/2.).rem_euclid(std::f32::consts::TAU);
        Some((angle/std::f32::consts::FRAC_PI_4) as usize)
    }
    fn favorites(&self)->Vec<&str> {
        let values=self.companion.config["emoteFavorites"].as_array();let mut result=Vec::new();
        if let Some(values)=values {for value in values {if let Some(name)=value.as_str() && emotes::NAMES.contains(&name) && !result.contains(&name) {result.push(name);if result.len()==8{break;}}}}
        for name in &emotes::NAMES {if result.len()<8 && !result.contains(name){result.push(name);}}
        result
    }
    pub(super) fn cubeon_emote_wheel(&mut self,batch:&mut HudBatch) {
        let (cx,cy)=(batch.width/2.,batch.height/2.);let r=(batch.height.min(batch.width)/3.).clamp(35.,75.);let selected=self.wheel_selection();
        let favorites=self.favorites();
        for (i,name) in favorites.iter().enumerate() {
            let a=i as f32*std::f32::consts::FRAC_PI_4;let x=cx+a.sin()*r-30.;let y=cy-a.cos()*r-10.;
            button(batch,&self.gui.atlas,self.cursor,[x,y,60.,20.],name);
            if selected==Some(i) {batch.fill(&self.gui.atlas,x,y,60.,1.,rgba(125,225,191,255));}
        }
        batch.text(&self.gui.atlas,"Emotes · release B or click",cx-75.,cy-5.,u32::MAX,true);
    }
    pub(super) fn cubeon_emote_choose(&mut self) {
        if let Some(i)=self.wheel_selection() {let name=self.favorites()[i].to_owned();self.cubeon_play_emote(&name);}
        self.screen=Screen::Playing;
    }
}
fn button(batch:&mut HudBatch,atlas:&cubeon_client::hud::HudAtlas,cursor:(f32,f32),rect:[f32;4],label:&str) {
    ui::button(batch,atlas,rect[0],rect[1],rect[2],rect[3],&cubeon_client::text::Text::literal(label),true,ui::hovered(cursor,rect[0],rect[1],rect[2],rect[3]));
}
