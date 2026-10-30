import assert from 'node:assert/strict';
import { DatabaseSync } from 'node:sqlite';
import { Hub } from './cubeon-friends.js';
const db = new DatabaseSync(':memory:');
let writes = 0;
const sql = { exec(query, ...args) {
  if (!args.length && query.includes('CREATE TABLE')) { db.exec(query); return {toArray:()=>[]}; }
  if (/^\s*(INSERT|UPDATE|DELETE)/i.test(query)) writes++;
  const rows=db.prepare(query).all(...args);
  return {toArray:()=>rows};
}};
const sockets=[];
const ctx={storage:{sql},getWebSockets:()=>sockets};
let hub=new Hub(ctx,{});
async function connect(name, username) {
 const ws={attachment:{ip:name},frames:[],deserializeAttachment(){return this.attachment;},
 serializeAttachment(a){this.attachment=a;},send(raw){this.frames.push(JSON.parse(raw));},close(){}};
 sockets.push(ws);
 await send(ws,{t:'hello',name,secret:'test-secret-'+name,minecraft_username:username});
 return ws;
}
const send=(ws,msg)=>hub.webSocketMessage(ws,JSON.stringify(msg));
const actor=await connect('Player_11111111','BlueFox');
const viewer=await connect('Player_22222222','RubyFox');
const other=await connect('Player_33333333','GreenFox');
const room='a'.repeat(64), uuid='12345678-1234-1234-1234-123456789abc';
await send(actor,{t:'emote_room',room});
await send(viewer,{t:'emote_room',room});
await send(other,{t:'emote_room',room:'b'.repeat(64)});
assert.equal(actor.frames.at(-1).ready,true);
const clear=()=>sockets.forEach(s=>s.frames.length=0);
const writesBefore=writes;
clear();
await send(actor,{t:'emote',uuid,emote:'wave',serial:1,username:'ForgedName'});
assert.equal(viewer.frames.length,1);
assert.deepEqual(viewer.frames[0],{t:'emote',room,uuid,username:'BlueFox',emote:'wave',serial:1,age:0});
assert.equal(other.frames.length,0,'different servers are isolated');
assert.equal(actor.frames.length,1,'sender receives authoritative echo');
clear();
await send(actor,{t:'emote',uuid,emote:'dance',serial:2});
assert.equal(viewer.frames.length,0,'rapid repeat is dropped');
await send(actor,{t:'emote',uuid,emote:'stop',serial:3});
assert.equal(viewer.frames.at(-1).emote,'stop');
clear();
for (const frame of [{emote:'unknown',serial:4},{emote:'wave',serial:-1},
 {emote:'wave',serial:1.5},{emote:'wave',serial:4,uuid:'bad'}])
 await send(actor,{t:'emote',uuid,...frame});
assert.equal(viewer.frames.length,0,'malformed requests never fan out');
await send(actor,{t:'emote',uuid,emote:'dance',serial:5});
clear();
await send(other,{t:'emote_room',room});
assert.equal(other.frames.at(-1).emote,'dance','joining a room receives active emote');
assert.equal(other.frames.at(-1).serial,5);
clear();
// New DO instance has no memory of the emote; socket attachments retain it.
hub=new Hub(ctx,{});
await send(viewer,{t:'emote_room',room});
assert.equal(viewer.frames.at(-1).emote,'dance','hibernation preserves active pose');
clear();
for (const [index, emote] of ['clap','laugh','sit','celebrate'].entries()) {
 await send(actor,{t:'emote',uuid,emote:'stop',serial:10+index*2});
 clear();
 await send(actor,{t:'emote',uuid,emote,serial:11+index*2});
 assert.equal(viewer.frames.at(-1).emote,emote,'new emote relays to Cubeon viewers');
 assert.equal(viewer.frames.at(-1).username,'BlueFox','new emotes use trusted account identity');
}
await send(actor,{t:'emote',uuid,emote:'stop',serial:20});
await send(actor,{t:'emote',uuid,emote:'sit',serial:21});
actor.attachment.emote.started=Date.now()-5000;
clear();
await send(viewer,{t:'emote_room',room});
assert.equal(viewer.frames.at(-1).emote,'sit','late join sees Sit throughout its six-second duration');
actor.attachment.emote.started=Date.now()-6500;
clear();
await send(viewer,{t:'emote_room',room});
assert.equal(viewer.frames.filter(f=>f.t==='emote').length,0,'finished Sit is not replayed');
clear();
await send(actor,{t:'emote_room',room:'b'.repeat(64)});
assert.equal(viewer.frames.at(-1).emote,'stop','leaving cancels the old room pose');
assert.equal(actor.attachment.emote,null);
clear();
actor.attachment.emoteRoomUntil=Date.now()-1;
await send(actor,{t:'emote',uuid,emote:'wave',serial:6});
assert.equal(viewer.frames.length,0,'expired context cannot broadcast');
const unauth={attachment:{},frames:[],deserializeAttachment(){return this.attachment;},send(x){this.frames.push(x);}};
await send(unauth,{t:'emote',uuid,emote:'wave',serial:7});
assert.equal(unauth.frames.length,0,'unauthenticated messages ignored');
assert.equal(writes,writesBefore,'emotes never write SQL history');
console.log('Emote sync: unrelated Cubeon viewers, room isolation, trusted username, stop, expiry, malformed requests, late join, hibernation and no SQL writes passed.');
