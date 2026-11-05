//! Cubeon analytic poses, applied only after vanilla player model animation.
use crate::mobs::{Mob,anim::Poses};
use std::{cell::RefCell,collections::HashMap,time::Instant};
pub const NAMES:[&str;10]=["wave","dance","bow","salute","shrug","point","clap","laugh","sit","celebrate"];
pub const DURATIONS:[f32;10]=[3.,6.,3.,3.,2.5,3.,4.,4.,6.,4.5];
#[derive(Clone)] struct Active {id:usize,serial:i64,at:Instant,age:f32}
thread_local! {static ACTIVE:RefCell<HashMap<u32,Active>>=RefCell::new(HashMap::new());}
pub fn clear() {ACTIVE.with(|a|a.borrow_mut().clear());}
pub fn event(entity:u32,name:&str,serial:i64,age:f32) {
    ACTIVE.with(|active| {
        let mut active=active.borrow_mut();
        if name=="stop" {active.remove(&entity);return;}
        let Some(id)=NAMES.iter().position(|n|*n==name) else{return;};
        if !age.is_finite()||age<0.||age>=DURATIONS[id] {return;}
        if active.get(&entity).is_some_and(|a|a.serial==serial) {return;}
        if active.len()>=128 && !active.contains_key(&entity) {return;}
        active.insert(entity,Active{id,serial,at:Instant::now(),age});
    });
}
pub fn playing(entity:u32)->bool {ACTIVE.with(|a|a.borrow().get(&entity).is_some_and(|v|v.age+v.at.elapsed().as_secs_f32()<DURATIONS[v.id]))}
fn smooth(t:f32)->f32 {let t=t.clamp(0.,1.);t*t*(3.-2.*t)}
pub struct Pose {pub angles:[[f32;3];6],pub mask:u8,pub weight:f32,pub drop:f32,pub bow:bool}
impl Pose {
    fn set(&mut self,i:usize,x:f32,y:f32,z:f32) {self.angles[i]=[x,y,z];self.mask|=1<<i;}
    pub fn sample(id:usize,age:f32)->Self {
        let duration=DURATIONS.get(id).copied().unwrap_or(0.);
        let weight=smooth((age/0.25).min((duration-age)/0.35));
        let mut p=Self {angles:[[0.;3];6],mask:0,weight,drop:0.,bow:false};let beat=(age*8.).sin();let sway=(age*4.).sin();
        match id {
            0=>{p.set(2,-2.45+beat*0.22,-0.3,0.5+beat*0.35);p.set(3,0.1,0.,-0.08);p.set(0,0.,0.,beat*0.04);}
            1=>{let other=(age*8.).cos();p.set(1,-0.06+beat*0.06,sway*0.2,other*0.04);p.set(2,-1.3-other*0.7,0.2,0.5-beat*0.25);p.set(3,-1.3+other*0.7,-0.2,-0.5-beat*0.25);p.set(4,beat*0.4,0.,0.);p.set(5,-beat*0.4,0.,0.);p.set(0,-0.08+beat*0.08,sway*0.12,0.);}
            2=>{p.bow=true;p.set(1,0.5,0.,0.);p.set(0,0.3,0.,0.);p.set(2,-1.5,-0.1,0.15);p.set(3,-2.,-0.3,-0.4);}
            3=>{p.set(2,-2.6,-0.2,0.3);p.set(3,0.12,0.,-0.06);p.set(0,0.08,0.,0.);}
            4=>{p.set(2,0.4,-0.4,1.1);p.set(3,0.4,0.4,-1.1);p.set(0,-0.18,0.,sway*0.03);}
            5=>{p.set(2,-std::f32::consts::FRAC_PI_2,-0.05,0.12);p.set(3,0.12,0.,-0.14);p.set(0,-0.06,0.,0.);}
            6=>{let close=0.5-0.5*(age*9.5).cos();let hands=0.12+0.34*smooth(close);p.set(2,-1.35-close*0.08,-hands,-0.04);p.set(3,-1.35-close*0.08,hands,0.04);p.set(0,0.05+close*0.025,0.,0.);p.set(1,-0.015+close*0.02,0.,0.);}
            7=>{let chuckle=(age*12.).sin();p.set(2,-2.55+chuckle*0.035,-0.5,-0.14);p.set(3,-0.65,0.55,0.18);p.set(0,-0.16+chuckle*0.045,-0.04,sway*0.02);p.set(1,0.075+chuckle*0.025,0.,chuckle*0.018);}
            8=>{p.drop=10.*weight;p.set(4,-std::f32::consts::FRAC_PI_2,-0.12,0.06);p.set(5,-std::f32::consts::FRAC_PI_2,0.12,-0.06);p.set(2,-0.48,-0.08,-0.06);p.set(3,-0.48,0.08,0.06);p.set(1,0.04,0.,0.);p.set(0,0.06+sway*0.012,0.,0.);}
            9=>{let pump=(age*7.).sin();p.set(2,-2.8+pump*0.15,-0.12,0.3);p.set(3,-2.8-pump*0.15,0.12,-0.3);p.set(0,-0.13+pump*0.02,sway*0.04,0.);p.set(1,-0.04,sway*0.05,pump*0.025);p.set(4,pump*0.06,0.,0.);p.set(5,-pump*0.06,0.,0.);}
            _=>{}
        } p
    }
    pub fn apply(&self,poses:&mut Poses) {
        let body=*poses.get("body");
        let frame=glam::Mat3::from_rotation_z(body[5])*glam::Mat3::from_rotation_y(body[4]);
        let hip=glam::Vec3::new(body[0],body[1],body[2])+frame*glam::Vec3::new(0.,12.*body[3].cos(),12.*body[3].sin());
        let bend=frame*glam::Mat3::from_rotation_x(self.angles[1][0]*self.weight)*frame.transpose();
        for (i,name) in ["head","body","right_arm","left_arm","right_leg","left_leg"].iter().enumerate() {
            let p=poses.get(name);
            if self.bow && i<4 {
                let at=glam::Vec3::new(p[0],p[1],p[2]);let changed=hip+bend*(at-hip);p[0]=changed.x;p[1]=changed.y;p[2]=changed.z;
            }
            p[1]+=self.drop;
            if self.mask&(1<<i)!=0 {for axis in 0..3 {
                p[axis+3]+=if i<2 {self.angles[i][axis]*self.weight}else{(self.angles[i][axis]-p[axis+3])*self.weight};
            }}
        }
    }
}
pub fn apply(m:&Mob,poses:&mut Poses) {
    if &*m.kind.id!="minecraft:player" || m.health<=0. || m.extra.passenger || m.extra.fall_flying || m.extra.swim.amount(1.)>0. {return;}
    ACTIVE.with(|active| {
        let active=active.borrow();let Some(a)=active.get(&m.id) else{return;};let age=a.age+a.at.elapsed().as_secs_f32();
        if age<DURATIONS[a.id] {Pose::sample(a.id,age).apply(poses);}
    });
}
#[cfg(test)] mod tests {
    use super::*;
    #[test] fn poses_end_and_stay_finite() {for id in 0..10 {for age in [0.,0.1,1.,DURATIONS[id]] {let p=Pose::sample(id,age);assert!(p.angles.iter().flatten().all(|v|v.is_finite()));if age==DURATIONS[id] {assert_eq!(p.weight,0.);}}}}
    #[test] fn duplicate_events_do_not_restart() {clear();event(1,"wave",2,1.);event(1,"wave",2,0.);ACTIVE.with(|a|assert_eq!(a.borrow()[&1].age,1.));event(1,"stop",3,0.);assert!(!playing(1));}
}
