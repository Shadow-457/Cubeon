(function(){
  var CB=window.CB,MT=window.MinecraftTextures;if(!CB||!MT)return;
  var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  var D=CB.D,ic=CB.ic,esc=CB.esc,ed=$('#ed'),codec=window.TextureCodec,TA=window.TextureAnimation;
  var SKIN=[Object.assign({},MT.resolve('entity/player/wide/steve'),{id:'skin',n:'Skin',cat:'Skin'})];

  /* ---------- state ---------- */
  var E={p:null,catalog:MT,loading:false,docs:{},pending:{},open:[],cur:null,last:null,doc:null,faceModel:null,tool:'pencil',color:'#7AC24A',alpha:100,size:1,mx:false,my:false,zoom:16,grid:true,uv:true,cat:'',q:'',page:0,res:[],ri:0,lb:0};
  var BC={},hover=null,drag=null,activeToken=0;
  var ec=$('#ec'),eo=$('#eo'),ectx=ec.getContext('2d'),octx=eo.getContext('2d'),wrap=$('#edWrap');
  var preview=new window.MinecraftPreview(function(id){return getDoc(id)});
  var packSession=null;
  var picker=new window.ColorChooser({button:$('#edCol'),read:function(){return {hex:E.color,alpha:E.alpha}},
    onChange:function(h,a){setColor(h,false,true);setAlpha(a,true)}});
  var animationControls=new window.AnimationControls({read:function(){return E.cur==='preview'?null:E.doc},change:changeAnimation,select:selectAnimation});
  function ents(){return E.p.type==='skin'?SKIN:E.catalog.entries}
  function entry(id){return E.p.type==='skin'?(id==='skin'?SKIN[0]:null):E.catalog.resolve(id)}
  function docSize(e){
    var scale=E.p.type==='skin'?1:(Number(E.p.size)||16)/16;
    return {w:Math.max(1,Math.round(e.w*scale)),h:Math.max(1,Math.round(e.h*scale))};
  }
  function clone(id){return new ImageData(new Uint8ClampedArray(id.data),id.width,id.height)}
  function refreshEntry(d){
    d.e=TA.effectiveEntry(d.source,d.animationOverride,d.w,d.h);
    try{d.layout=TA.layout(d.e)}catch(_){d.layout=null}
  }
  function viewRect(d){return d.frameView&&d.layout?TA.frameRect(d.layout,d.frame):{x:0,y:0,w:d.w,h:d.h}}
  function base(e,w,h){
    var key=(e.url||e.src)+':'+w+':'+h;
    if(!BC[key])BC[key]=MT.load(e).then(function(img){
      var cv=document.createElement('canvas');cv.width=w;cv.height=h;
      var ctx=cv.getContext('2d');ctx.imageSmoothingEnabled=false;ctx.drawImage(img,0,0,w,h);
      return ctx.getImageData(0,0,w,h);
    });
    return BC[key];
  }
  function dec(edit,project){return codec.decode(edit,project)}
  async function getDoc(id){
    var e=entry(id);if(!e)throw new Error('Texture not found: '+id);
    id=e.id;
    if(E.docs[id]){E.docs[id].used=performance.now();return E.docs[id]}
    if(E.pending[id])return E.pending[id];
    var project=E.p,docs=E.docs,pending=E.pending,size=docSize(e);
    pending[id]=(async function(){
      var data=project.edits[id]?dec(project.edits[id],project):clone(await base(e,size.w,size.h));
      var cv=document.createElement('canvas');cv.width=data.width;cv.height=data.height;
      var ctx=cv.getContext('2d');ctx.putImageData(data,0,0);
      var override=TA.hasOverride(project,id)?TA.copy(project.animations[id]):undefined,view=project.animationView&&project.animationView[id];
      var doc={id:id,source:e,e:e,w:data.width,h:data.height,data:data,animationOverride:override,
        frame:view&&Number.isInteger(view.frame)?view.frame:0,frameView:view?!!view.frames:override!=null,
        undo:[],redo:[],cv:cv,ctx:ctx,zoom:0,version:0,used:performance.now()};
      refreshEntry(doc);return docs[id]=doc;
    })();
    try{return await pending[id]}finally{delete pending[id]}
  }
  function pruneDocs(){
    var ids=Object.keys(E.docs).sort(function(a,b){return E.docs[a].used-E.docs[b].used});
    var total=ids.reduce(function(n,id){return n+E.docs[id].data.data.byteLength},0);
    ids.forEach(function(id){if(total>67108864&&E.docs[id]!==E.doc){total-=E.docs[id].data.data.byteLength;delete E.docs[id]}});
  }
  function drawEnt(cv,e){
    if(!e)return;
    var doc=E.docs[e.id],edit=E.p.edits[e.id],source;
    if(doc){doc.ctx.putImageData(doc.data,0,0);source=doc.cv}
    else if(edit){
      var data=dec(edit,E.p);source=document.createElement('canvas');source.width=data.width;source.height=data.height;
      source.getContext('2d').putImageData(data,0,0);
    }
    if(source)e=TA.effectiveEntry(e,doc?doc.animationOverride:TA.hasOverride(E.p,e.id)?E.p.animations[e.id]:undefined,source.width,source.height);
    MT.draw(cv,e,source);
  }

  /* ---------- pixels & tools ---------- */
  function rgba(){var h=E.color;return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16),Math.round(E.alpha*2.55)]}
  function hex2(n){return ('0'+n.toString(16)).slice(-2)}
  function setPx(x,y,c){var d=E.doc,r=viewRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h)return;var a=d.data.data,i=(y*d.w+x)*4;a[i]=c[0];a[i+1]=c[1];a[i+2]=c[2];a[i+3]=c[3]}
  function apply(x,y){
    var d=E.doc,t=drag.t,r=viewRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h)return;
    if(t==='eraser')setPx(x,y,[0,0,0,0]);
    else if(t==='light'||t==='dark'){var a=d.data.data,i=(y*d.w+x)*4;if(a[i+3]){var k=t==='light'?1.14:.86;a[i]=Math.min(255,a[i]*k);a[i+1]=Math.min(255,a[i+1]*k);a[i+2]=Math.min(255,a[i+2]*k)}}
    else setPx(x,y,rgba());
  }
  function stamp(x,y){var s=E.size,o=(s-1)>>1;for(var j=0;j<s;j++)for(var i=0;i<s;i++)apply(x-o+i,y-o+j)}
  function plot(x,y){
    var d=E.doc,r=viewRect(d);stamp(x,y);
    if(E.mx)stamp(2*r.x+r.w-1-x,y);if(E.my)stamp(x,2*r.y+r.h-1-y);if(E.mx&&E.my)stamp(2*r.x+r.w-1-x,2*r.y+r.h-1-y);
  }
  function line(a,b,skip){
    var x0=a[0],y0=a[1],x1=b[0],y1=b[1],dx=Math.abs(x1-x0),dy=-Math.abs(y1-y0),sx=x0<x1?1:-1,sy=y0<y1?1:-1,er=dx+dy,first=true;
    for(;;){if(!(first&&skip))plot(x0,y0);first=false;if(x0===x1&&y0===y1)break;var e2=2*er;if(e2>=dy){er+=dy;x0+=sx}if(e2<=dx){er+=dx;y0+=sy}}
  }
  function rectShape(a,b,filled){
    var x0=Math.min(a[0],b[0]),x1=Math.max(a[0],b[0]),y0=Math.min(a[1],b[1]),y1=Math.max(a[1],b[1]),x,y;
    for(y=y0;y<=y1;y++)for(x=x0;x<=x1;x++)if(filled||x===x0||x===x1||y===y0||y===y1)plot(x,y);
  }
  function fill(x,y){
    var d=E.doc,w=d.w,h=d.h,a=d.data.data,r=viewRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h)return;
    var i0=(y*w+x)*4,t=[a[i0],a[i0+1],a[i0+2],a[i0+3]],n=rgba();
    if(t[0]===n[0]&&t[1]===n[1]&&t[2]===n[2]&&t[3]===n[3])return;
    var st=[x,y],seen=new Uint8Array(r.w*r.h);
    while(st.length){
      var cy=st.pop(),cx=st.pop();if(cx<r.x||cy<r.y||cx>=r.x+r.w||cy>=r.y+r.h)continue;
      var k=(cy-r.y)*r.w+cx-r.x;if(seen[k])continue;var i=(cy*w+cx)*4;
      if(a[i]!==t[0]||a[i+1]!==t[1]||a[i+2]!==t[2]||a[i+3]!==t[3])continue;
      seen[k]=1;a[i]=n[0];a[i+1]=n[1];a[i+2]=n[2];a[i+3]=n[3];
      st.push(cx+1,cy,cx-1,cy,cx,cy+1,cx,cy-1);
    }
  }
  function pickAt(c){
    var d=E.doc,r=viewRect(d);if(c[0]<r.x||c[1]<r.y||c[0]>=r.x+r.w||c[1]>=r.y+r.h)return;
    var a=d.data.data,i=(c[1]*d.w+c[0])*4;if(!a[i+3])return;
    setColor('#'+hex2(a[i])+hex2(a[i+1])+hex2(a[i+2]),true);
    setAlpha(Math.round(a[i+3]/255*100));
  }
  function checkpoint(d){return {data:clone(d.data),animation:TA.copy(d.animationOverride),frame:d.frame,frameView:d.frameView}}
  function pushUndo(d){d.undo.push(checkpoint(d));var bytes=d.undo.reduce(function(sum,item){return sum+item.data.data.byteLength},0);while(d.undo.length>1&&(d.undo.length>60||bytes>25165824))bytes-=d.undo.shift().data.data.byteLength;d.redo.length=0;sync()}
  function restoreCheckpoint(d,item){d.data=item.data;d.animationOverride=TA.copy(item.animation);d.frame=item.frame;d.frameView=item.frameView;redraw();setZoom(fitZoom(d));commit(d)}
  function redraw(){
    var d=E.doc;d.w=d.data.width;d.h=d.data.height;
    if(d.cv.width!==d.w||d.cv.height!==d.h){d.cv.width=d.w;d.cv.height=d.h}
    refreshEntry(d);var r=viewRect(d),resized=ec.width!==r.w||ec.height!==r.h;
    if(resized){ec.width=r.w;ec.height=r.h}
    d.ctx.putImageData(d.data,0,0);ectx.clearRect(0,0,ec.width,ec.height);ectx.putImageData(d.data,-r.x,-r.y,r.x,r.y,r.w,r.h);d.version++;
    if(resized)setZoom(E.zoom);
  }
  function undo(){var d=E.doc;if(!d||!d.undo.length)return;if(drag)end();d.redo.push(checkpoint(d));restoreCheckpoint(d,d.undo.pop())}
  function redo(){var d=E.doc;if(!d||!d.redo.length)return;if(drag)end();d.undo.push(checkpoint(d));restoreCheckpoint(d,d.redo.pop())}
  async function transform(kind){
    var d=E.doc;if(!d)return;
    var token=activeToken;
    if(kind==='reset'){
      var size=docSize(d.source),original=clone(await base(d.source,size.w,size.h));
      if(token!==activeToken||E.doc!==d)return;
      pushUndo(d);d.data=original;d.animationOverride=undefined;d.frame=0;d.frameView=false;redraw();setZoom(fitZoom(d));commit(d);return;
    }
    try{var result=TA.transformAnimation(d,kind);pushUndo(d);applyAnimationChange(d,result)}catch(error){CB.toast(error.message)}
  }
  function applyAnimationChange(d,result){
    var previous=viewRect(d);
    if(result.data)d.data=result.data;
    if(Object.prototype.hasOwnProperty.call(result,'animation'))d.animationOverride=TA.copy(result.animation);
    if(result.frame!==undefined)d.frame=result.frame;
    if(result.frameView!==undefined)d.frameView=result.frameView;
    redraw();var next=viewRect(d);if(previous.w!==next.w||previous.h!==next.h)setZoom(fitZoom(d));commit(d);
  }
  function changeAnimation(action,value){
    var d=E.doc;if(!d||E.p.type==='skin'||E.cur==='preview')return;if(drag)end();
    try{if(action==='toggle'&&!TA.supported(d.e))return;var result=TA.change(d,action,value);if(!result){animationControls.refresh();return}pushUndo(d);applyAnimationChange(d,result)}
    catch(error){CB.toast(error.message);animationControls.refresh()}
  }
  function selectAnimation(frame,frameView){
    var d=E.doc;if(!d||!d.layout)return;if(drag)end();
    var changedView=d.frameView!==frameView;if(frame!=null)d.frame=Math.max(0,Math.min(d.layout.steps.length-1,frame));d.frameView=frameView;
    redraw();if(changedView)setZoom(fitZoom(d));else setZoom(E.zoom);sync();persist();
  }
  function commit(d){
    var p=E.p,now=Date.now();
    p.edits[d.id]=codec.encode(d.data);p.edited=now;p.open=E.open.slice();p.cur=E.cur;p.last=E.last;
    if(d.animationOverride!==undefined){p.animations=p.animations||{};p.animations[d.id]=TA.copy(d.animationOverride)}else if(p.animations)delete p.animations[d.id];
    rememberAnimationView(d);
    d.ctx.putImageData(d.data,0,0);
    var t=document.createElement('canvas');t.width=t.height=16;var c=t.getContext('2d');c.imageSmoothingEnabled=false;
    if(p.type==='skin')c.drawImage(d.cv,8,8,8,8,0,0,16,16);
    else{var f=MT.frame(d.e,0,d.w,d.h),scale=Math.min(16/f.w,16/f.h);c.drawImage(d.cv,f.x,f.y,f.w,f.h,(16-f.w*scale)/2,(16-f.h*scale)/2,f.w*scale,f.h*scale)}
    p.thumb=t.toDataURL();
    if(now-E.lb>30000){CB.bump();E.lb=now}
    CB.save();sync();renderTabs();renderLeft();
    if(E.cur==='preview')buildPreview();
  }
  function paintSwatch(){
    var values=[1,3,5].map(function(i){return parseInt(E.color.slice(i,i+2),16)});
    $('#edCol span').style.backgroundColor='rgba('+values.join(',')+','+E.alpha/100+')';
  }
  function setColor(h,fromPick,fromChooser){
    E.color=h.toLowerCase();$('#edHex').value=E.color.toUpperCase();paintSwatch();
    $$('.cw',ed).forEach(function(b){b.setAttribute('aria-pressed',b.dataset.c.toLowerCase()===E.color)});
    if(picker&&!fromChooser)picker.set(E.color,E.alpha);
  }
  function setAlpha(a,fromChooser){
    E.alpha=Math.max(0,Math.min(100,Number(a)));$('#edAlpha').value=E.alpha;$('#edAlphaValue').value=E.alpha+'%';paintSwatch();
    if(picker&&!fromChooser)picker.set(E.color,E.alpha);
  }
  function pushRecent(){
    var r=D.set.recent||(D.set.recent=[]),c=E.color;
    var i=r.indexOf(c);if(i>-1)r.splice(i,1);r.unshift(c);if(r.length>10)r.length=10;renderPal();
  }

  /* ---------- canvas events ---------- */
  function cellAt(e){var r=ec.getBoundingClientRect(),d=E.doc,b=viewRect(d);return [b.x+Math.floor((e.clientX-r.left)/r.width*b.w),b.y+Math.floor((e.clientY-r.top)/r.height*b.h)]}
  function hud(c){
    var d=E.doc;if(!d)return;var r=viewRect(d),inb=c&&c[0]>=r.x&&c[1]>=r.y&&c[0]<r.x+r.w&&c[1]<r.y+r.h;
    $('#edHud').textContent=(inb?'x '+(c[0]-r.x)+'  y '+(c[1]-r.y)+'  ·  ':'')+(d.frameView&&d.layout?'Frame '+(d.frame+1)+'  ·  ':'')+r.w+'×'+r.h+'  ·  '+Number(E.zoom.toFixed(3))+'×';
  }
  ec.addEventListener('pointerdown',function(e){
    if(!E.doc||e.button>0)return;
    var d=E.doc,c=cellAt(e),t=e.altKey?'pick':E.tool;
    try{ec.setPointerCapture(e.pointerId)}catch(_){}
    if(t==='pick'){pickAt(c);drag={t:'pick'};return}
    pushUndo(d);drag={t:t,s:c,l:c};
    if(t==='fill'){fill(c[0],c[1])}
    else if(t==='line'||t==='rect'){drag.snap=new Uint8ClampedArray(d.data.data);if(t==='line')line(c,c);else rectShape(c,c,e.shiftKey)}
    else plot(c[0],c[1]);
    redraw();
    if(t==='fill')end();
  });
  ec.addEventListener('pointermove',function(e){
    if(!E.doc)return;
    var c=cellAt(e);hover=c;hud(c);
    if(drag){
      var d=E.doc;
      if(drag.t==='pick')pickAt(c);
      else if(drag.t==='line'||drag.t==='rect'){d.data.data.set(drag.snap);if(drag.t==='line')line(drag.s,c);else rectShape(drag.s,c,e.shiftKey);redraw()}
      else if(c[0]!==drag.l[0]||c[1]!==drag.l[1]){line(drag.l,c,true);drag.l=c;redraw()}
    }
    ovl();
  });
  function end(){if(!drag)return;var t=drag.t;drag=null;if(t==='pick')return;pushRecent();commit(E.doc)}
  ec.addEventListener('pointerup',end);ec.addEventListener('pointercancel',end);
  ec.addEventListener('pointerleave',function(){hover=null;ovl();hud(null)});
  $('#edArea').addEventListener('wheel',function(e){if(!E.doc)return;e.preventDefault();setZoom(E.zoom*(e.deltaY<0?1.15:1/1.15))},{passive:false});

  /* ---------- view ---------- */
  var UV=[['Head',0,0,32,16],['Body',16,16,24,16],['R leg',0,16,16,16],['R arm',40,16,16,16],['L leg',16,48,16,16],['L arm',32,48,16,16]],FR=[[8,8,8,8],[20,20,8,12],[44,20,4,12],[4,20,4,12],[20,52,4,12],[36,52,4,12]];
  function ovl(){
    var d=E.doc;octx.clearRect(0,0,eo.width,eo.height);if(!d)return;var z=E.zoom,r=viewRect(d);
    if(E.p.type==='skin'&&E.uv){
      octx.lineWidth=2;octx.strokeStyle='rgba(79,138,28,.95)';octx.fillStyle='rgba(20,30,10,.85)';octx.font='700 12px sans-serif';
      UV.forEach(function(u){octx.strokeRect(u[1]*z+1,u[2]*z+1,u[3]*z-2,u[4]*z-2);octx.fillText(u[0],u[1]*z+6,u[2]*z+16)});
      octx.setLineDash([5,4]);octx.strokeStyle='rgba(255,255,255,.95)';
      FR.forEach(function(f){octx.strokeRect(f[0]*z+1,f[1]*z+1,f[2]*z-2,f[3]*z-2)});octx.setLineDash([]);
    }
    if(hover&&E.tool!=='fill'&&hover[0]>=r.x&&hover[1]>=r.y&&hover[0]<r.x+r.w&&hover[1]<r.y+r.h){
      var s=E.size,o=(s-1)>>1;octx.lineWidth=2;octx.strokeStyle='rgba(0,0,0,.85)';octx.strokeRect((hover[0]-r.x-o)*z+1,(hover[1]-r.y-o)*z+1,s*z-2,s*z-2);
      octx.strokeStyle='rgba(255,255,255,.9)';octx.lineWidth=1;octx.strokeRect((hover[0]-r.x-o)*z+2,(hover[1]-r.y-o)*z+2,s*z-4,s*z-4);
    }
  }
  function fitZoom(d){var a=$('#edArea'),r=viewRect(d),z=Math.min((a.clientWidth-48)/r.w,(a.clientHeight-48)/r.h,48);return Math.max(.125,z>=1?Math.floor(z):Math.floor(z*8)/8)}
  function setZoom(z){
    var d=E.doc;if(!d)return;z=Math.max(.125,Math.min(48,Math.round(z*8)/8));E.zoom=z;d.zoom=z;
    var r=viewRect(d),wd=r.w*z,ht=r.h*z;
    ec.style.width=wd+'px';ec.style.height=ht+'px';eo.width=wd;eo.height=ht;eo.style.width=wd+'px';eo.style.height=ht+'px';
    wrap.style.setProperty('--z',z+'px');wrap.classList.toggle('nogrid',!E.grid||z<6);
    $('#edZoom').value=z;hud(null);ovl();
  }

  /* ---------- left list ---------- */
  function list(){var q=E.q.trim().toLowerCase();return ents().filter(function(e){return MT.within(e,E.cat)&&MT.matches(e,q)})}
  function pageSize(){var g=$('#edGrid'),h=g.clientHeight,w=g.clientWidth;if(!h||!w)return 12;var cw=(w-28-16)/3,rows=Math.max(1,Math.floor((h-12)/(cw+30)));return rows*3}
  function renderLeft(){
    var skin=E.p.type==='skin';$('#edCat').style.display=skin?'none':'';
    $('#edFolders').style.display=skin?'none':'';
    $('#edCat').value=E.cat.split('/')[0];
    var nav=E.catalog.navigation(E.cat);if($('#edFolders').innerHTML!==nav)$('#edFolders').innerHTML=nav;
    var all=list(),ps=pageSize(),pages=Math.max(1,Math.ceil(all.length/ps));
    if(E.page>=pages)E.page=pages-1;if(E.page<0)E.page=0;
    var items=all.slice(E.page*ps,E.page*ps+ps),g=$('#edGrid');
    g.innerHTML=items.map(function(e){return '<button class="tx" type="button" data-id="'+e.id+'" aria-pressed="'+(E.cur===e.id||(E.cur==='preview'&&E.last===e.id))+'" title="'+esc(e.src)+' · '+e.w+'×'+e.h+'"><canvas data-id="'+e.id+'"></canvas>'+(E.p.edits[e.id]?'<i class="dot"></i>':'')+'<span>'+esc(e.n)+'</span></button>'}).join('')||'<div class="mu" style="grid-column:1/-1;padding:20px 4px">No textures match.</div>';
    $$('canvas[data-id]',g).forEach(function(cv){drawEnt(cv,entry(cv.dataset.id))});
    $('#edCount').textContent=all.length.toLocaleString()+(all.length===1?' texture':' textures');
    var h='<button class="pgb" type="button" data-pg="'+(E.page-1)+'" aria-label="Previous page"'+(E.page===0?' disabled':'')+'>'+ic('chevl')+'</button>';
    var st=Math.max(0,Math.min(E.page-2,pages-5)),en=Math.min(pages,st+5);
    for(var i=st;i<en;i++)h+='<button class="pgb" type="button" data-pg="'+i+'" aria-current="'+(i===E.page)+'">'+(i+1)+'</button>';
    h+='<button class="pgb" type="button" data-pg="'+(E.page+1)+'" aria-label="Next page"'+(E.page>=pages-1?' disabled':'')+'>'+ic('chevr')+'</button>';
    $('#edPager').innerHTML=pages>1?h:'';
    $('#edPager').style.display=pages>1?'':'none';
  }

  /* ---------- tabs ---------- */
  function renderTabs(){
    var tabs=$('#edTabs');
    var h=E.open.map(function(id){var e=entry(id);return '<button class="tab'+(E.cur===id?' on':'')+'" type="button" role="tab" aria-selected="'+(E.cur===id)+'" data-id="'+id+'"><canvas data-id="'+id+'"></canvas><span>'+esc(e.n)+'</span><span class="x" role="button" aria-label="Close '+esc(e.n)+'" data-x="'+id+'">'+ic('close')+'</span></button>'}).join('');
    h+='<button class="tab pvt'+(E.cur==='preview'?' on':'')+'" type="button" role="tab" aria-selected="'+(E.cur==='preview')+'" data-id="preview">'+ic('cube')+'<span>3D preview</span></button>';
    tabs.innerHTML=h;
    $$('canvas[data-id]',tabs).forEach(function(cv){drawEnt(cv,entry(cv.dataset.id))});
  }
  function rememberAnimationView(d){if(!d)return;E.p.animationView=E.p.animationView||{};E.p.animationView[d.id]={frame:d.frame,frames:d.frameView}}
  function persist(){rememberAnimationView(E.doc);E.p.open=E.open.slice();E.p.cur=E.cur;E.p.last=E.last;E.p.folder=E.cat;CB.save()}
  async function activate(id){
    picker.close(false);
    if(id&&id!=='preview'){var e=entry(id);if(!e)return;id=e.id}
    if(E.faceModel&&id&&id!=='preview'&&!Object.values(E.faceModel.faces).some(function(f){return f.id===id||f.overlay===id}))E.faceModel=null;
    if(drag)end();
    rememberAnimationView(E.doc);var token=++activeToken;preview.stop();animationControls.stop();
    E.cur=id;if(id&&id!=='preview')E.last=id;
    E.doc=null;
    var pv=id==='preview';
    if(pv){ed.classList.remove('l-open','r-open');$('#pvW').innerHTML='';$('#pvT').textContent='Loading preview…'}
    $('#edPv').classList.toggle('on',pv);
    $('#edArea').style.display='none';$('#edHud').style.display='none';
    $('#edEmpty').style.display=pv?'none':'flex';
    $('#edEmpty b').textContent=id?'Loading texture…':'No texture open';
    $('#edEmpty span').textContent=id?'': 'Pick one from the list on the left, or search for it above.';
    $('#edRight').classList.add('off');$('#faceBar').style.display='none';
    persist();renderTabs();renderLeft();sync();
    var target=pv?E.last:id;
    if(!target){if(pv){$('#pvW').innerHTML='';$('#pvT').textContent='Open a texture to preview it'}return}
    try{
      var d=await getDoc(target);if(token!==activeToken)return;
      E.doc=d;$('#edPath').textContent=d.e.src;$('#edPath').title=d.e.src+' · '+d.w+'×'+d.h;
      if(pv){await buildPreview()}
      else{
        $('#edEmpty').style.display='none';$('#edArea').style.display='';$('#edHud').style.display='';
        $('#edRight').classList.remove('off');redraw();setZoom(d.zoom||fitZoom(d));
        if(d.e.cat==='block'){
          var model=E.faceModel||MT.blockModel(d.e,E.catalog),faces=[model.faces.top.id,model.faces.front.id,model.faces.bottom.id];
          $('#faceBar').style.display=new Set(faces).size>1?'':'none';
          $$('[data-face]',$('#faceBar')).forEach(function(b){var face=b.dataset.face==='sides'?'front':b.dataset.face;b.setAttribute('aria-pressed',model.faces[face].id===d.id)});
        }
      }
      sync();pruneDocs();
    }catch(err){
      if(token!==activeToken)return;
      if(pv)$('#pvT').textContent=err.message;
      else{$('#edEmpty b').textContent='Could not load texture';$('#edEmpty span').textContent=err.message}
    }
  }
  function openTex(id,keepModel){var e=entry(id);if(!e)return;if(!keepModel)E.faceModel=null;id=e.id;ed.classList.remove('l-open','r-open');if(E.open.indexOf(id)<0)E.open.push(id);activate(id)}
  function closeTab(id){
    var i=E.open.indexOf(id);if(i<0)return;E.open.splice(i,1);
    var n=E.open[i]||E.open[i-1]||null;if(E.last===id)E.last=n;if(E.cur===id)activate(n);else if(E.cur==='preview')activate('preview');else{persist();renderTabs()}
  }

  /* ---------- 3D preview ---------- */
  function buildPreview(){return preview.build(E.doc,E.p.type==='skin',Motion.reduced(),E.faceModel||(E.doc.e.cat==='block'?MT.blockModel(E.doc.e,E.catalog):null))}

  /* ---------- search ---------- */
  function renderRes(){
    var q=$('#edQ').value.trim().toLowerCase(),box=$('#edRes');
    if(!q){box.classList.remove('on');E.res=[];return}
    E.res=ents().filter(function(e){return MT.matches(e,q)}).slice(0,8);if(E.ri>=E.res.length)E.ri=0;
    box.innerHTML=E.res.length?E.res.map(function(e,i){return '<button class="rs'+(i===E.ri?' on':'')+'" type="button" data-id="'+e.id+'"><canvas data-id="'+e.id+'"></canvas><span>'+esc(e.n)+'</span><small>'+esc(e.folder)+'/</small></button>'}).join(''):'<div class="rs none">No textures match</div>';
    box.classList.add('on');$$('canvas[data-id]',box).forEach(function(cv){drawEnt(cv,entry(cv.dataset.id))});
  }
  function pickRes(id){
    $('#edQ').value='';E.q='';E.cat=entry(id).folder;$('#edRes').classList.remove('on');
    var all=list(),ps=pageSize(),ix=all.map(function(e){return e.id}).indexOf(id);E.page=ix>-1?Math.floor(ix/ps):0;
    openTex(id);
  }
  $('#edQ').addEventListener('input',function(){E.q=this.value;E.page=0;E.ri=0;renderLeft();renderRes()});
  $('#edQ').addEventListener('keydown',function(e){
    if(e.key==='ArrowDown'){e.preventDefault();E.ri=Math.min(E.res.length-1,E.ri+1);renderRes()}
    else if(e.key==='ArrowUp'){e.preventDefault();E.ri=Math.max(0,E.ri-1);renderRes()}
    else if(e.key==='Enter'){if(E.res[E.ri])pickRes(E.res[E.ri].id)}
    else if(e.key==='Escape'){this.value='';E.q='';E.page=0;renderLeft();renderRes();this.blur()}
  });
  $('#edQ').addEventListener('blur',function(){setTimeout(function(){$('#edRes').classList.remove('on')},160)});
  $('#edQ').addEventListener('focus',renderRes);
  $('#edRes').addEventListener('mousedown',function(e){e.preventDefault()});
  $('#edRes').addEventListener('click',function(e){var b=e.target.closest('.rs[data-id]');if(b)pickRes(b.dataset.id)});

  /* ---------- panels ---------- */
  var DEF=['#000000','#1D1D21','#474F52','#9D9D97','#F9FFFE','#B02E26','#F9801D','#FED83D','#80C71F','#5E7C16','#3AB3DA','#3C44AA','#8932B8','#C74EBD','#F38BAA','#835432'];
  function cw(c){return '<button class="cw" type="button" data-c="'+c+'" aria-label="'+c+'" aria-pressed="'+(c.toLowerCase()===E.color)+'" style="background:'+c+'"></button>'}
  function renderPal(){
    var pr=DEF;
    $('#edPal').innerHTML=pr.map(cw).join('');
    var r=D.set.recent||[];$('#edRec').innerHTML=r.length?r.map(cw).join(''):'<span class="mu" style="font-size:12px">Colors you use show up here.</span>';
  }
  function sync(){
    $$('.tb',$('#edTools')).forEach(function(b){b.setAttribute('aria-pressed',b.dataset.t===E.tool)});
    $$('.sg',$('#edSize')).forEach(function(b){b.setAttribute('aria-pressed',+b.dataset.v===E.size)});
    $('#edCat').value=E.cat.split('/')[0];
    $$('.tg[data-e]',ed).forEach(function(b){b.setAttribute('aria-checked',String(!!E[b.dataset.e]))});
    $('#rowUV').style.display=E.p.type==='skin'?'':'none';
    var d=E.doc;$('#edRight').classList.toggle('off',!d||E.cur==='preview');$('#edUndo').disabled=!d||!d.undo.length;$('#edRedo').disabled=!d||!d.redo.length;
    $('#edUndo').style.opacity=$('#edUndo').disabled?.4:1;$('#edRedo').style.opacity=$('#edRedo').disabled?.4:1;
    $('#edAlpha').value=E.alpha;
    animationControls.refresh();
  }
  ed.addEventListener('click',function(e){
    var t=e.target,b;
    if(t.closest('#edBack')){close();return}
    if(E.loading)return;
    if(t.closest('#edDetails')){picker.close(false);CB.openDetails(E.p);return}
    if(t.closest('#edExport')){picker.close(false);window.ResourcePacks.exportProject(E.p);return}
    if(b=t.closest('#edL')){ed.classList.toggle('l-open');ed.classList.remove('r-open');return}
    if(b=t.closest('#edR')){ed.classList.toggle('r-open');ed.classList.remove('l-open');return}
    if(t.closest('#edC')&&(ed.classList.contains('l-open')||ed.classList.contains('r-open'))){ed.classList.remove('l-open','r-open')}
    if(b=t.closest('#edTools .tb')){E.tool=b.dataset.t;sync();ovl();return}
    if(b=t.closest('#edSize .sg')){E.size=+b.dataset.v;sync();ovl();return}
    if(b=t.closest('#edFolders [data-folder]')){E.cat=b.dataset.folder;E.page=0;renderLeft();sync();persist();return}
    if(b=t.closest('#faceBar [data-face]')){if(E.doc){E.faceModel=E.faceModel||MT.blockModel(E.doc.e,E.catalog);var face=b.dataset.face==='sides'?'front':b.dataset.face;openTex(E.faceModel.faces[face].id,true)}return}
    if(b=t.closest('.tg[data-e]')){var k=b.dataset.e;E[k]=!E[k];if(k==='grid'||k==='uv'){setZoom(E.zoom)}sync();return}
    if(b=t.closest('.cw')){setColor(b.dataset.c);return}
    if(b=t.closest('[data-pg]')){if(b.disabled)return;E.page=+b.dataset.pg;renderLeft();return}
    if(b=t.closest('.tx[data-id]')){openTex(b.dataset.id);return}
    if(b=t.closest('[data-x]')){e.stopPropagation();closeTab(b.dataset.x);return}
    if(b=t.closest('#edTabs .tab')){if(b.dataset.id!=='preview')E.faceModel=null;activate(b.dataset.id);return}
    if(b=t.closest('[data-a]')){transform(b.dataset.a);return}
    if(t.closest('#edFit')){if(E.doc)setZoom(fitZoom(E.doc));return}
    if(t.closest('#edUndo')){undo();return}
    if(t.closest('#edRedo')){redo();return}
  });
  $('#edCat').innerHTML=MT.options();
  $('#edCat').addEventListener('change',function(){E.cat=this.value;E.page=0;renderLeft();persist()});
  $('#edZoom').addEventListener('input',function(){setZoom(+this.value)});
  $('#edAlpha').addEventListener('input',function(){setAlpha(+this.value)});
  $('#edHex').addEventListener('input',function(){var v=this.value.trim();if(v[0]!=='#')v='#'+v;if(/^#[0-9a-f]{6}$/i.test(v))setColor(v)});
  window.addEventListener('resize',function(){if(ed.classList.contains('show'))renderLeft()});
  document.addEventListener('keydown',function(e){
    if(!ed.classList.contains('show'))return;
    if(e.defaultPrevented||$('#modal').classList.contains('show')||!picker.panel.hidden||E.loading)return;
    var t=e.target,typing=t&&(t.tagName==='TEXTAREA'||(t.tagName==='INPUT'&&t.type!=='range'&&t.type!=='color'));
    var mod=e.ctrlKey||e.metaKey,k=e.key.toLowerCase();
    if(typing)return;
    if(mod&&k==='s'){e.preventDefault();CB.save();window.LocalStore.flush();return}
    if(mod&&k==='z'){e.preventDefault();if(e.shiftKey)redo();else undo();return}
    if(mod&&k==='y'){e.preventDefault();redo();return}
    if(mod)return;
    var map={b:'pencil',e:'eraser',g:'fill',i:'pick',l:'line',r:'rect',u:'light',d:'dark'};
    if(map[k]){E.tool=map[k];sync();ovl()}
    else if(k==='['){E.size=Math.max(1,E.size-1);sync();ovl()}
    else if(k===']'){E.size=Math.min(3,E.size+1);sync();ovl()}
    else if(k==='='||k==='+'){setZoom(E.zoom*1.15)}
    else if(k==='-'){setZoom(E.zoom/1.15)}
  });

  /* ---------- open / close ---------- */
  function refreshDetails(){
    if(!E.p)return;
    $('#edName').textContent=E.p.name;$('#edDetails').hidden=E.p.type==='skin';$('#edPackLabel').textContent=E.p.type==='skin'?'Skin':'Texture pack';
    $('.local-note',ed).textContent=E.p.type==='skin'?'Autosaves on this device · export a PNG':'Autosaves on this device · export a ZIP to share';
    $('#edExport').setAttribute('aria-label',E.p.type==='skin'?'Export skin PNG':'Export Minecraft resource pack ZIP');$('#edExport').title=E.p.type==='skin'?'Export skin PNG':'Export resource pack ZIP';renderPal();
  }
  async function open(p){
    await CB.ready;
    if(drag)end();
    var token=++activeToken;preview.stop();picker.close(false);animationControls.stop();
    if(packSession){packSession.release();packSession=null;}
    E.loading=true;E.doc=null;E.catalog=MT;$('#edQ').disabled=true;
    E.p=p;p.edits=p.edits||{};E.docs={};E.pending={};BC={};E.faceModel=null;E.open=[];E.cur=null;E.last=null;E.q='';E.page=0;E.tool='pencil';E.size=1;E.mx=E.my=false;E.alpha=100;animationControls.refresh();
    $('#edName').textContent=p.name;$('#edPath').textContent='';$('#edArea').style.display='none';$('#edPv').classList.remove('on');$('#edRight').classList.add('off');
    $('#edEmpty').style.display='flex';$('#edEmpty b').textContent='Opening local project…';$('#edEmpty span').textContent='';
    ed.classList.remove('l-open','r-open');ed.classList.add('show');document.body.style.overflow='hidden';Motion.editor(ed);
    $('#app>.main').inert=true;$('#app>.sb').inert=true;
    try{
      var session=await window.ResourcePacks.openCatalog(p);
      if(token!==activeToken){session.release();return;}
      packSession=session;E.catalog=session.catalog;
    }catch(error){
      if(token===activeToken){E.loading=false;$('#edEmpty b').textContent='Could not open project';$('#edEmpty span').textContent=error.message;}
      throw error;
    }
    E.loading=false;$('#edQ').disabled=false;$('#edCat').innerHTML=E.catalog.options();
    var migrated={};Object.keys(p.edits).forEach(function(id){var e=entry(id);migrated[e?e.id:id]=p.edits[id]});p.edits=migrated;
    $('#edQ').value='';$('#edRes').classList.remove('on');
    E.open=(p.open||[]).map(function(id){var e=entry(id);return e&&e.id}).filter(Boolean);
    E.open=Array.from(new Set(E.open));
    var initial=entry(p.type==='skin'?'skin':p.texture||p.block||'block/grass_block_top'),first=initial?initial.id:ents()[0].id;
    var selected=p.cur&&entry(p.cur),cur=p.cur==='preview'?'preview':selected?selected.id:null;
    if(!E.open.length){E.open=[first];cur=first}
    if(cur===null||(cur!=='preview'&&E.open.indexOf(cur)<0))cur=E.open[0];
    var last=entry(p.last);E.last=cur==='preview'?(last&&E.open.includes(last.id)?last.id:E.open[0]):cur;
    E.cat=p.type==='skin'?'':(E.catalog.folders[p.folder]?p.folder:entry(E.last).folder);
    preview.reset();setColor((D.set.recent||[])[0]||'#7ac24a');setAlpha(100);refreshDetails();return activate(cur);
  }
  function close(){
    if(drag)end();activeToken++;preview.stop();picker.close(false);animationControls.stop();
    if(E.p&&!E.loading)persist();
    ed.classList.remove('show','l-open','r-open');document.body.style.overflow='';
    $('#app>.main').inert=false;$('#app>.sb').inert=false;
    if(packSession){packSession.release();packSession=null;}
    E.doc=null;E.p=null;E.loading=false;E.docs={};E.pending={};BC={};E.catalog=MT;drag=null;CB.save();CB.renderAll();
  }
  window.Ed={open:open,close:close,refreshDetails:refreshDetails,prepareExport:function(){if(drag)end();CB.save()}};
})();
