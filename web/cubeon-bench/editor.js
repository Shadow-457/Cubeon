(function(){
  var CB=window.CB,MT=window.MinecraftTextures;if(!CB||!MT)return;
  var $=function(s,r){return (r||document).querySelector(s)},$$=function(s,r){return [].slice.call((r||document).querySelectorAll(s))};
  var D=CB.D,ic=CB.ic,esc=CB.esc,ed=$('#ed'),codec=window.TextureCodec,TA=window.TextureAnimation,TD=window.TextureDepth;
  var SKIN=[Object.assign({},MT.resolve('entity/player/wide/steve'),{id:'skin',n:'Skin',cat:'Skin'})];

  /* ---------- state ---------- */
  var E={p:null,catalog:MT,loading:false,docs:{},pending:{},open:[],cur:null,last:null,doc:null,faceModel:null,tool:'pencil',color:'#7AC24A',alpha:100,size:1,mx:false,my:false,zoom:16,grid:true,uv:true,cat:'',q:'',page:0,res:[],ri:0,lb:0};
  var BC={},hover=null,drag=null,activeToken=0,clipboard=null;
  var panning=null,lastTool=null,PALETTE_PAGE=16,frameClipboard=null,spaceHand=null,depthClipboard=null;
  E.depthEditing=false;E.depthAction='raise';E.depthAmount=10;E.depthValue=50;E.depthSoftness=0;E.depthView='texture';
  var TOOL_HELP={pencil:['Draw','Drag on the canvas to draw.'],eraser:['Erase','Drag to erase pixels.'],fill:['Fill','Click to fill connected pixels of the same color.'],pick:['Pick','Click a pixel to reuse its color.'],line:['Line','Drag to draw a line.'],rect:['Rectangle','Drag an outline. Hold Shift to fill it.'],ellipse:['Ellipse','Drag an oval. Hold Shift to fill it.'],select:['Select','Drag to select pixels, then copy or clear.'],light:['Lighten','Drag to make pixels lighter.'],dark:['Darken','Drag to make pixels darker.']};
  var ec=$('#ec'),eo=$('#eo'),ectx=ec.getContext('2d'),octx=eo.getContext('2d'),wrap=$('#edWrap'),tintCanvas=document.createElement('canvas');
  tintCanvas.id='et';tintCanvas.setAttribute('aria-hidden','true');wrap.insertBefore(tintCanvas,eo);
  var depthOverlay=document.createElement('canvas');depthOverlay.id='depthOverlay';depthOverlay.hidden=true;depthOverlay.setAttribute('aria-hidden','true');wrap.insertBefore(depthOverlay,eo);
  var preview=new window.MinecraftPreview(function(id){return getDoc(id)});
  var packSession=null;
  var picker=new window.ColorChooser({button:$('#edCol'),read:function(){return {hex:E.color,alpha:E.alpha}},
    onChange:function(h,a){setColor(h,false,true);setAlpha(a,true)}});
  var animationControls=new window.AnimationControls({read:function(){return E.cur==='preview'?null:E.doc},change:changeAnimation,select:selectAnimation,clipboard:frameAction});
  var surfaceStudio=new window.SurfaceStudio({read:function(){return E.doc},rect:function(){var d=E.doc;return d.layout?TA.frameRect(d.layout,d.frame):{x:0,y:0,w:d.w,h:d.h}},
    apply:changeSurface,closed:function(){if(E.cur==='preview')buildPreview()}});
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
  function paintRect(d){
    var r=viewRect(d),s=d.selection;if(!s)return r;
    var x=Math.max(r.x,s.x),y=Math.max(r.y,s.y);return {x:x,y:y,w:Math.max(0,Math.min(r.x+r.w,s.x+s.w)-x),h:Math.max(0,Math.min(r.y+r.h,s.y+s.h)-y)};
  }
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
        frame:view&&Number.isInteger(view.frame)?view.frame:0,frameView:view?!!view.frames:!!(override!==undefined?override:e.animation),
        undo:[],redo:[],cv:cv,ctx:ctx,zoom:0,fitMode:true,version:0,used:performance.now()};
      doc.viewTint=project.tintView&&Object.prototype.hasOwnProperty.call(project.tintView,id)?!!project.tintView[id]:D.set.naturalColors!==false;
      doc.surface=window.TextureSurface.settings(project.surfaces&&Object.prototype.hasOwnProperty.call(project.surfaces,id)?project.surfaces[id]:null);
      doc.committed=codec.encode(data);doc.committedAnimation=JSON.stringify(override);doc.committedSurface=JSON.stringify(doc.surface);refreshEntry(doc);return docs[id]=doc;
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
    MT.draw(cv,Object.assign({},e,{viewTint:doc?doc.viewTint:E.p.tintView&&E.p.tintView[e.id]!==undefined?E.p.tintView[e.id]:D.set.naturalColors!==false}),source);
  }

  /* ---------- pixels & tools ---------- */
  function rgba(){var h=E.color;return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16),Math.round(E.alpha*2.55)]}
  function hex2(n){return ('0'+n.toString(16)).slice(-2)}
  function setPx(x,y,c){var d=E.doc,r=paintRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h||!TD.contains(d.selection,x,y))return;var a=d.data.data,i=(y*d.w+x)*4;a[i]=c[0];a[i+1]=c[1];a[i+2]=c[2];a[i+3]=c[3]}
  function apply(x,y){
    var d=E.doc,t=drag.t,r=paintRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h||!TD.contains(d.selection,x,y))return;
    if(t==='eraser')setPx(x,y,[0,0,0,0]);
    else if(t==='light'||t==='dark'){var a=d.data.data,i=(y*d.w+x)*4;if(a[i+3]){var k=t==='light'?1.14:.86;a[i]=Math.min(255,a[i]*k);a[i+1]=Math.min(255,a[i+1]*k);a[i+2]=Math.min(255,a[i+2]*k)}}
    else setPx(x,y,rgba());
  }
  function depthOperation(){return drag.t==='eraser'?'reset':drag.t==='light'?'raise':drag.t==='dark'?'lower':E.depthAction;}
  function stamp(x,y){
    if(E.depthEditing){TD.brush(TD.layer(E.doc),drag.depthStroke,x,y,E.size,E.depthSoftness,E.doc.selection,viewRect(E.doc),depthOperation(),E.depthAmount,E.depthValue,drag.pressure);return;}
    var s=E.size,o=(s-1)>>1;for(var j=0;j<s;j++)for(var i=0;i<s;i++)apply(x-o+i,y-o+j)
  }
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
  function ellipse(a,b,filled){
    var x0=Math.min(a[0],b[0]),x1=Math.max(a[0],b[0]),y0=Math.min(a[1],b[1]),y1=Math.max(a[1],b[1]);
    var rx=(x1-x0+1)/2,ry=(y1-y0+1)/2,cx=(x0+x1)/2,cy=(y0+y1)/2;
    function inside(x,y){return Math.pow((x-cx)/rx,2)+Math.pow((y-cy)/ry,2)<=1}
    for(var y=y0;y<=y1;y++)for(var x=x0;x<=x1;x++)if(inside(x,y)&&(filled||!inside(x-1,y)||!inside(x+1,y)||!inside(x,y-1)||!inside(x,y+1)))plot(x,y);
  }
  function selectArea(a,b){
    var r=viewRect(E.doc),x=Math.max(r.x,Math.min(a[0],b[0])),y=Math.max(r.y,Math.min(a[1],b[1]));
    E.doc.selection={x:x,y:y,w:Math.min(r.x+r.w-1,Math.max(a[0],b[0]))-x+1,h:Math.min(r.y+r.h-1,Math.max(a[1],b[1]))-y+1};sync();ovl();
  }
  function selectionAction(action){
    var d=E.doc;if(!d||E.cur==='preview')return;if(drag)end();
    if(action==='all'){d.selection=Object.assign({},viewRect(d));sync();ovl();return}
    if(action==='none'){d.selection=null;sync();ovl();return}
    if(E.depthEditing){depthSelectionAction(action);return}
    var r=paintRect(d);if(!r.w||!r.h)return;
    if(action==='copy'||action==='cut'){
      clipboard=new ImageData(r.w,r.h);
      for(var y=0;y<r.h;y++)for(var x=0;x<r.w;x++)if(TD.contains(d.selection,r.x+x,r.y+y))clipboard.data.set(d.data.data.subarray(((r.y+y)*d.w+r.x+x)*4,((r.y+y)*d.w+r.x+x)*4+4),(y*r.w+x)*4);
      CB.toast('Copied '+r.w+'×'+r.h+' pixels. Paste into any open texture.');
      if(action==='copy'){sync();return}
    }
    if(action==='paste'){
      if(!clipboard)return;pushUndo(d);
      for(var y=0;y<Math.min(r.h,clipboard.height);y++)for(var x=0;x<Math.min(r.w,clipboard.width);x++){
        var i=(y*clipboard.width+x)*4;if(clipboard.data[i+3])setPx(r.x+x,r.y+y,clipboard.data.subarray(i,i+4));
      }
    }else{
      pushUndo(d);for(var y=r.y;y<r.y+r.h;y++)for(var x=r.x;x<r.x+r.w;x++)setPx(x,y,[0,0,0,0]);
    }
    d.depthLayer=null;redraw();commit(d);ovl();
  }
  function depthSelectionAction(action){
    var d=E.doc,r=paintRect(d),map=TD.layer(d);if(!r.w||!r.h)return;
    if(action==='copy'||action==='cut'){
      depthClipboard=new ImageData(r.w,r.h);
      for(var y=0;y<r.h;y++)for(var x=0;x<r.w;x++)if(TD.contains(d.selection,r.x+x,r.y+y))depthClipboard.data.set(map.data.subarray(((r.y+y)*d.w+r.x+x)*4,((r.y+y)*d.w+r.x+x)*4+4),(y*r.w+x)*4);
      if(action==='copy'){CB.toast('Depth selection copied.');return;}
    }
    if(action==='paste'&&!depthClipboard)return;
    pushUndo(d);
    if(action==='paste'){
      for(var y=0;y<Math.min(r.h,depthClipboard.height);y++)for(var x=0;x<Math.min(r.w,depthClipboard.width);x++){
        var i=(y*depthClipboard.width+x)*4;if(depthClipboard.data[i+3]&&TD.contains(d.selection,r.x+x,r.y+y))map.data.set(depthClipboard.data.subarray(i,i+4),((r.y+y)*d.w+r.x+x)*4);
      }
    }else TD.adjust(map,d.selection,viewRect(d),'reset',E.depthAmount,E.depthValue);
    TD.save(d);redraw();commit(d);ovl();
  }
  function setDepthMode(on){
    if(E.cur==='preview')return activate(E.last||E.open[0]).then(function(){setDepthMode(on)});
    var d=E.doc;if(!d||E.p.type==='skin'||!window.TextureSurface.supported(d.data))return;
    if(drag)end();picker.close(false);E.depthEditing=on;E.hand=false;E.tool=on?'select':'pencil';lastTool=null;
    ed.classList.toggle('depth-editing',on);
    redraw();sync();ovl();
    if(on&&innerWidth<=900)openDepthPanel();
  }
  function openDepthPanel(){ed.dataset.toolSection='tools';ed.classList.add('r-open');ed.classList.remove('l-open','frames-open');animationControls.layoutRail();$('#edRight').scrollTop=$('#surfaceTools').offsetTop-64;}
  function adjustDepth(operation){
    var d=E.doc;if(!d||!E.depthEditing||!d.selection)return;if(drag)end();
    pushUndo(d);TD.adjust(TD.layer(d),d.selection,viewRect(d),operation,E.depthAmount,E.depthValue);TD.save(d);redraw();commit(d);ovl();
  }
  function fill(x,y){
    if(E.depthEditing){
      var d=E.doc,r=viewRect(d),map=TD.layer(d),level=map.data[(y*d.w+x)*4],stack=[x,y],visited=new Uint8Array(d.w*d.h);
      while(stack.length){
        var py=stack.pop(),px=stack.pop();if(px<r.x||py<r.y||px>=r.x+r.w||py>=r.y+r.h||!TD.contains(d.selection,px,py))continue;
        var index=py*d.w+px;if(visited[index]||drag.depthStroke.before[index*4]!==level)continue;visited[index]=1;
        TD.pixel(map,drag.depthStroke,px,py,depthOperation(),E.depthAmount,E.depthValue,1);stack.push(px+1,py,px-1,py,px,py+1,px,py-1);
      }
      return;
    }
    var d=E.doc,w=d.w,h=d.h,a=d.data.data,r=paintRect(d);if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h)return;
    var i0=(y*w+x)*4,t=[a[i0],a[i0+1],a[i0+2],a[i0+3]],n=rgba();
    if(t[0]===n[0]&&t[1]===n[1]&&t[2]===n[2]&&t[3]===n[3])return;
    var st=[x,y],seen=new Uint8Array(r.w*r.h);
    while(st.length){
      var cy=st.pop(),cx=st.pop();if(cx<r.x||cy<r.y||cx>=r.x+r.w||cy>=r.y+r.h)continue;
      var k=(cy-r.y)*r.w+cx-r.x;if(seen[k]||!TD.contains(d.selection,cx,cy))continue;var i=(cy*w+cx)*4;
      if(a[i]!==t[0]||a[i+1]!==t[1]||a[i+2]!==t[2]||a[i+3]!==t[3])continue;
      seen[k]=1;a[i]=n[0];a[i+1]=n[1];a[i+2]=n[2];a[i+3]=n[3];
      st.push(cx+1,cy,cx-1,cy,cx,cy+1,cx,cy-1);
    }
  }
  function pickAt(c){
    var d=E.doc,r=viewRect(d);if(c[0]<r.x||c[1]<r.y||c[0]>=r.x+r.w||c[1]>=r.y+r.h)return;
    if(E.depthEditing){E.depthValue=Math.round(TD.layer(d).data[(c[1]*d.w+c[0])*4]/255*100);$('#depthValue').value=E.depthValue;return;}
    var a=d.data.data,i=(c[1]*d.w+c[0])*4;if(!a[i+3])return;
    setColor('#'+hex2(a[i])+hex2(a[i+1])+hex2(a[i+2]),true);
    setAlpha(Math.round(a[i+3]/255*100));
  }
  function checkpoint(d){return {data:clone(d.data),animation:TA.copy(d.animationOverride),surface:d.surface,frame:d.frame,frameView:d.frameView,selection:d.selection&&Object.assign({},d.selection)}}
  function historyBytes(items){
    var heights=new Set(),selections=new Set();return items.reduce(function(sum,item){
      var height=item.surface&&item.surface.height;if(height&&!heights.has(height.pixels)){heights.add(height.pixels);sum+=height.pixels.length*2;}
      var selection=item.selection;if(selection){
        if(selection.mask&&!selections.has(selection.mask)){selections.add(selection.mask);sum+=selection.mask.byteLength;}
        if(selection.edges&&!selections.has(selection.edges)){selections.add(selection.edges);sum+=selection.edges.length*64;}
      }
      return sum+item.data.data.byteLength;
    },0);
  }
  function pushUndo(d){d.undo.push(checkpoint(d));while(d.undo.length>1&&(d.undo.length>60||historyBytes(d.undo)>25165824))d.undo.shift();d.redo.length=0;sync()}
  function restoreCheckpoint(d,item){d.data=item.data;d.animationOverride=TA.copy(item.animation);d.surface=item.surface||null;d.depthLayer=null;d.frame=item.frame;d.frameView=item.frameView;d.selection=item.selection;redraw();setZoom(fitZoom(d),true);commit(d)}
  function changeSurface(value){
    var d=E.doc;if(!d||d.id==='skin')return false;
    var surface=window.TextureSurface.settings(value);
    if(JSON.stringify(surface)!==JSON.stringify(d.surface)){pushUndo(d);d.surface=surface;d.depthLayer=null;redraw();d.version++;}
    return commit(d);
  }
  function heightDocument(d){
    if(!d.surface||!d.surface.height)return null;
    return {data:window.TextureSurface.fit(codec.decode(d.surface.height),d.w,d.h),w:d.w,h:d.h,e:d.e,
      frame:d.frame,frameView:d.frameView,animationOverride:TA.copy(d.animationOverride)};
  }
  function heightChange(d,result){
    d.depthLayer=null;if(result&&result.data)d.surface=Object.assign({},d.surface,{height:codec.encode(result.data)});
  }
  function redraw(){
    var d=E.doc;d.w=d.data.width;d.h=d.data.height;
    if(E.depthEditing&&!window.TextureSurface.supported(d.data)){E.depthEditing=false;ed.classList.remove('depth-editing');}
    if(d.cv.width!==d.w||d.cv.height!==d.h){d.cv.width=d.w;d.cv.height=d.h}
    refreshEntry(d);var r=viewRect(d),resized=ec.width!==r.w||ec.height!==r.h;
    if(resized){ec.width=r.w;ec.height=r.h}
    var heightView=E.depthEditing&&E.depthView==='height';
    d.ctx.putImageData(d.data,0,0);ectx.clearRect(0,0,ec.width,ec.height);ectx.putImageData(heightView?TD.layer(d):d.data,-r.x,-r.y,r.x,r.y,r.w,r.h);d.version++;
    depthOverlay.hidden=!E.depthEditing||heightView;
    if(!depthOverlay.hidden){depthOverlay.width=r.w;depthOverlay.height=r.h;depthOverlay.getContext('2d').putImageData(TD.overlay(TD.layer(d)),-r.x,-r.y,r.x,r.y,r.w,r.h);}
    var color=MT.tintColor(d.e);tintCanvas.hidden=heightView||!color||!d.viewTint;
    if(!tintCanvas.hidden){tintCanvas.width=ec.width;tintCanvas.height=ec.height;tintCanvas.getContext('2d').putImageData(MT.tintImage(ectx.getImageData(0,0,ec.width,ec.height),color),0,0)}
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
      pushUndo(d);d.selection=null;d.data=original;d.surface=null;d.depthLayer=null;d.animationOverride=undefined;d.frame=0;d.frameView=false;redraw();setZoom(fitZoom(d),true);commit(d);return;
    }
    try{var result=TA.transformAnimation(d,kind),height=heightDocument(d),heightResult=height?TA.transformAnimation(height,kind):null;pushUndo(d);heightChange(d,heightResult);applyAnimationChange(d,result)}catch(error){CB.toast(error.message)}
  }
  function applyAnimationChange(d,result){
    d.selection=null;
    var previous=viewRect(d);
    if(result.data){d.data=result.data;d.depthLayer=null;}
    if(Object.prototype.hasOwnProperty.call(result,'animation'))d.animationOverride=TA.copy(result.animation);
    if(result.frame!==undefined)d.frame=result.frame;
    if(result.frameView!==undefined)d.frameView=result.frameView;
    redraw();var next=viewRect(d);if(previous.w!==next.w||previous.h!==next.h)setZoom(fitZoom(d),true);else hud(null);commit(d);
  }
  function changeAnimation(action,value){
    var d=E.doc;if(!d||E.p.type==='skin'||E.cur==='preview')return;if(drag)end();
    try{
      if(action==='toggle'&&!TA.supported(d.e))return;
      var result=TA.change(d,action,value);if(!result){animationControls.refresh();return}
      var height=['toggle','add','remove','paste'].includes(action)?heightDocument(d):null,heightResult=null;
      if(height){
        var heightValue=value;
        if(action==='paste')heightValue={data:value.height||window.TextureSurface.generate(value.data,{version:1,depth:40,shine:15,smooth:0,invert:false,metal:false}).base,time:value.time};
        heightResult=TA.change(height,action,heightValue);
      }
      pushUndo(d);heightChange(d,heightResult);applyAnimationChange(d,result);
    }
    catch(error){CB.toast(error.message);animationControls.refresh()}
  }
  function frameAction(action) {
    var d=E.doc;if(!d||!d.layout||E.cur==='preview')return;
    if(drag)end();
    if(action==='copy'||action==='cut') {
      if(action==='cut'&&d.layout.steps.length<=1){CB.toast('Keep at least one animation frame.');return}
      frameClipboard=TA.copyFrame(d);
      if(d.surface){
        var height=heightDocument(d),map=height?height.data:window.TextureSurface.generate(d.data,{version:1,depth:40,shine:15,smooth:0,invert:false,metal:false},d.e).base;
        frameClipboard.height=TA.crop(map,TA.frameRect(d.layout,d.frame));
      }
      CB.toast('Frame copied, including its duration. Paste to insert a new frame.');
      if(action==='cut')changeAnimation('remove');
    } else if(action==='paste') {
      if(!frameClipboard){CB.toast('Copy an animation frame first.');return}
      changeAnimation('paste',frameClipboard);
    } else if(action==='duplicate')changeAnimation('add');
    else if(action==='remove') {
      if(d.layout.steps.length<=1){CB.toast('Keep at least one animation frame.');return}
      changeAnimation('remove');
    }
  }
  function selectAnimation(frame,frameView){
    var d=E.doc;if(!d||!d.layout)return;if(drag)end();
    d.selection=null;var changedView=d.frameView!==frameView;if(frame!=null)d.frame=Math.max(0,Math.min(d.layout.steps.length-1,frame));d.frameView=frameView;
    redraw();if(changedView)setZoom(fitZoom(d),true);else setZoom(E.zoom);sync();persist();
  }
  function commit(d){
    var p=E.p,now=Date.now();
    if(d.surface&&!window.TextureSurface.supported(d.data)){
      d.surface=null;CB.toast('Depth was removed from this larger texture. Undo restores the previous texture and depth.');
    }
    var encoded=codec.encode(d.data),old=d.committed,animation=JSON.stringify(d.animationOverride),surface=JSON.stringify(d.surface);
    var changed=!old||old.w!==encoded.w||old.h!==encoded.h||old.pixels!==encoded.pixels||d.committedAnimation!==animation||d.committedSurface!==surface;
    d.committed=encoded;d.committedAnimation=animation;d.committedSurface=surface;
    p.edits[d.id]=encoded;p.edited=now;p.open=E.open.slice();p.cur=E.cur;p.last=E.last;
    if(d.animationOverride!==undefined){p.animations=p.animations||{};p.animations[d.id]=TA.copy(d.animationOverride)}else if(p.animations)delete p.animations[d.id];
    if(d.surface){p.surfaces=p.surfaces||Object.create(null);p.surfaces[d.id]=d.surface}else if(p.surfaces)delete p.surfaces[d.id];
    rememberAnimationView(d);
    d.ctx.putImageData(d.data,0,0);
    var t=document.createElement('canvas');t.width=t.height=16;var c=t.getContext('2d');c.imageSmoothingEnabled=false;
    if(p.type==='skin')c.drawImage(d.cv,8,8,8,8,0,0,16,16);
    else{var f=MT.frame(d.e,0,d.w,d.h),scale=Math.min(16/f.w,16/f.h);c.drawImage(d.cv,f.x,f.y,f.w,f.h,(16-f.w*scale)/2,(16-f.h*scale)/2,f.w*scale,f.h*scale)}
    p.thumb=t.toDataURL();
    p.thumbTexture=d.id;
    if(changed)CB.recordTextureEdit(p,d.id);
    var saved=CB.save();sync();renderTabs();renderLeft();
    if(E.cur==='preview'&&!surfaceStudio.opened)buildPreview();
    return saved;
  }
  function paintSwatch(){
    var values=[1,3,5].map(function(i){return parseInt(E.color.slice(i,i+2),16)});
    $('#edCol span').style.backgroundColor='rgba('+values.join(',')+','+E.alpha/100+')';
  }
  function setColor(h,fromPick,fromChooser){
    E.color=h.toLowerCase();$('#edHex').value=E.color.toUpperCase();paintSwatch();
    $$('.cw',ed).forEach(function(b){b.setAttribute('aria-pressed',b.dataset.c.toLowerCase()===E.color)});
    if(picker&&!fromChooser)picker.set(E.color,E.alpha);
    if(window.MobileEditor)window.MobileEditor.sync();
  }
  function setAlpha(a,fromChooser){
    E.alpha=Math.max(0,Math.min(100,Number(a)));$('#edAlpha').value=E.alpha;$('#edAlphaValue').value=Math.round(E.alpha)+'%';paintSwatch();
    if(picker&&!fromChooser)picker.set(E.color,E.alpha);
    if(window.MobileEditor)window.MobileEditor.sync();
  }
  function pushRecent(){
    var r=D.set.recent||(D.set.recent=[]),c=E.color;
    var i=r.indexOf(c);if(i>-1)r.splice(i,1);r.unshift(c);if(r.length>10)r.length=10;renderPal();
  }

  /* ---------- canvas events ---------- */
  function cellAt(e){var r=ec.getBoundingClientRect(),d=E.doc,b=viewRect(d);return [Math.max(b.x,Math.min(b.x+b.w-1,b.x+Math.floor((e.clientX-r.left)/r.width*b.w))),Math.max(b.y,Math.min(b.y+b.h-1,b.y+Math.floor((e.clientY-r.top)/r.height*b.h)))]}
  function hud(c){
    var d=E.doc;if(!d)return;var r=viewRect(d),inb=c&&c[0]>=r.x&&c[1]>=r.y&&c[0]<r.x+r.w&&c[1]<r.y+r.h;
    $('#edHud').textContent=inb?'Pixel '+(c[0]-r.x)+', '+(c[1]-r.y):r.w+' × '+r.h+' pixels';
    if(inb&&E.depthEditing)$('#edHud').textContent+=' · Height '+Math.round(TD.layer(d).data[(c[1]*d.w+c[0])*4]/255*100)+'%';
  }
  ec.addEventListener('pointerdown',function(e){
    if(!E.doc||e.button>0||E.hand)return;
    ec.focus({preventScroll:true});
    var d=E.doc,c=cellAt(e),t=e.altKey?'pick':E.tool;
    try{ec.setPointerCapture(e.pointerId)}catch(_){}
    if(t==='pick'){pickAt(c);drag={t:'pick'};return}
    if(t==='select'){drag={t:t,s:c,l:c};selectArea(c,c);return}
    if(t==='lasso'){drag={t:t,points:[[c[0],c[1]]],l:c};d.selection=null;sync();return;}
    pushUndo(d);drag={t:t,s:c,l:c,pressure:e.pointerType==='pen'?e.pressure||1:1};
    if(E.depthEditing)drag.depthStroke=TD.stroke(TD.layer(d));
    if(t==='fill'){fill(c[0],c[1])}
    else if(t==='line'||t==='rect'||t==='ellipse'){drag.snap=new Uint8ClampedArray(E.depthEditing?TD.layer(d).data:d.data.data);if(t==='line')line(c,c);else if(t==='ellipse')ellipse(c,c,e.shiftKey);else rectShape(c,c,e.shiftKey)}
    else plot(c[0],c[1]);
    redraw();
    if(t==='fill')end();
  });
  ec.addEventListener('pointermove',function(e){
    if(!E.doc)return;
    var c=cellAt(e);hover=c;hud(c);
    if(drag){
      var d=E.doc;
      if(drag.depthStroke)drag.pressure=e.pointerType==='pen'?e.pressure||1:1;
      if(drag.t==='pick')pickAt(c);
      else if(drag.t==='select'){selectArea(drag.s,c)}
      else if(drag.t==='lasso'){if((c[0]!==drag.l[0]||c[1]!==drag.l[1])&&drag.points.length<4096){drag.points.push(c);drag.l=c;}}
      else if(drag.t==='line'||drag.t==='rect'||drag.t==='ellipse'){(E.depthEditing?TD.layer(d).data:d.data.data).set(drag.snap);if(drag.depthStroke)drag.depthStroke.weights.fill(0);if(drag.t==='line')line(drag.s,c);else if(drag.t==='ellipse')ellipse(drag.s,c,e.shiftKey);else rectShape(drag.s,c,e.shiftKey);redraw()}
      else if(c[0]!==drag.l[0]||c[1]!==drag.l[1]){line(drag.l,c,true);drag.l=c;redraw()}
    }
    ovl();
  });
  function end(){
    if(!drag)return;var t=drag.t;
    if(t==='lasso'){E.doc.selection=TD.lasso(drag.points,viewRect(E.doc));drag=null;sync();ovl();return;}
    drag=null;if(t==='pick'||t==='select')return;
    if(E.depthEditing)TD.save(E.doc);else{E.doc.depthLayer=null;pushRecent();}
    commit(E.doc);
  }
  ec.addEventListener('pointerup',end);ec.addEventListener('pointercancel',end);
  ec.addEventListener('pointerleave',function(){hover=null;ovl();hud(null)});
  var area=$('#edArea');
  area.addEventListener('pointerdown',function(e){
    if(!E.doc||!(E.hand&&e.button===0||e.button===1)||e.target.closest('button'))return;
    area.focus({preventScroll:true});
    e.preventDefault();e.stopPropagation();
    panning={id:e.pointerId,x:e.clientX,y:e.clientY,left:area.scrollLeft,top:area.scrollTop};
    area.setPointerCapture(e.pointerId);area.classList.add('is-panning');
  },true);
  area.addEventListener('pointermove',function(e){if(panning&&panning.id===e.pointerId){area.scrollLeft=panning.left-(e.clientX-panning.x);area.scrollTop=panning.top-(e.clientY-panning.y);}});
  function endPan(){if(!panning)return;var id=panning.id;panning=null;area.classList.remove('is-panning');if(area.hasPointerCapture(id))area.releasePointerCapture(id);}
  area.addEventListener('pointerup',endPan);area.addEventListener('pointercancel',endPan);area.addEventListener('lostpointercapture',endPan);window.addEventListener('blur',endPan);
  area.addEventListener('wheel',function(e){
    if(!E.doc)return;e.preventDefault();
    if(E.hand){area.scrollLeft+=e.deltaX;area.scrollTop+=e.deltaY;return;}
    if(e.shiftKey){area.scrollLeft+=e.deltaX||e.deltaY;return;}
    var before=ec.getBoundingClientRect(),x=(e.clientX-before.left)/before.width,y=(e.clientY-before.top)/before.height;
    setZoom(E.zoom*(e.deltaY<0?1.15:1/1.15),false);
    var after=ec.getBoundingClientRect();area.scrollLeft+=after.left+x*after.width-e.clientX;area.scrollTop+=after.top+y*after.height-e.clientY;
  },{passive:false});

  /* ---------- view ---------- */
  var UV=[['Head',0,0,32,16],['Body',16,16,24,16],['R leg',0,16,16,16],['R arm',40,16,16,16],['L leg',16,48,16,16],['L arm',32,48,16,16]],FR=[[8,8,8,8],[20,20,8,12],[44,20,4,12],[4,20,4,12],[20,52,4,12],[36,52,4,12]];
  function ovl(){
    var d=E.doc;octx.clearRect(0,0,eo.width,eo.height);if(!d)return;var z=E.zoom,r=viewRect(d);
    if(d.selection){
      var s=d.selection;octx.beginPath();
      if(s.mask)TD.outline(s).forEach(function(edge){octx.moveTo((edge[0]-r.x)*z,(edge[1]-r.y)*z);octx.lineTo((edge[2]-r.x)*z,(edge[3]-r.y)*z);});
      else octx.rect((s.x-r.x)*z+1,(s.y-r.y)*z+1,s.w*z-2,s.h*z-2);
      octx.lineWidth=2;octx.strokeStyle='#172610';octx.stroke();octx.setLineDash([5,4]);octx.strokeStyle='#fff';octx.stroke();octx.setLineDash([]);
    }
    if(drag&&drag.t==='lasso'){octx.beginPath();drag.points.forEach(function(point,index){var x=(point[0]-r.x)*z,y=(point[1]-r.y)*z;if(index)octx.lineTo(x,y);else octx.moveTo(x,y);});octx.closePath();octx.lineWidth=2;octx.strokeStyle='#fff';octx.setLineDash([5,4]);octx.stroke();octx.setLineDash([]);}
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
  function fitZoom(d){var a=$('#edArea'),r=viewRect(d),style=getComputedStyle(a),x=parseFloat(style.paddingLeft)+parseFloat(style.paddingRight),y=parseFloat(style.paddingTop)+parseFloat(style.paddingBottom),z=Math.min((a.clientWidth-x)/r.w,(a.clientHeight-y)/r.h,48);return Math.max(.125,z>=1?Math.floor(z):Math.floor(z*8)/8)}
  function fitViewport(){if(E.doc&&E.doc.fitMode&&!E.loading&&E.cur!=='preview'&&!ed.classList.contains('resizing'))setZoom(fitZoom(E.doc));}
  var fitFrame=0;
  if(window.ResizeObserver)new ResizeObserver(function(){if(!fitFrame)fitFrame=requestAnimationFrame(function(){fitFrame=0;fitViewport()})}).observe(area);
  function setZoom(z,fitMode){
    var d=E.doc;if(!d)return;z=Math.max(.125,Math.min(48,Math.round(z*8)/8));E.zoom=z;d.zoom=z;
    if(fitMode!==undefined)d.fitMode=fitMode;
    var r=viewRect(d),wd=r.w*z,ht=r.h*z;
    ec.style.width=wd+'px';ec.style.height=ht+'px';eo.width=wd;eo.height=ht;eo.style.width=wd+'px';eo.style.height=ht+'px';
    tintCanvas.style.width=wd+'px';tintCanvas.style.height=ht+'px';
    depthOverlay.style.width=wd+'px';depthOverlay.style.height=ht+'px';
    wrap.style.setProperty('--z',z+'px');wrap.classList.toggle('nogrid',!E.grid||z<6);
    $('#edZoom').value=z;$('#canvasZoomValue').textContent=Math.round(z*100)+'%';
    $('#canvasZoomOut').disabled=z<=.125;$('#canvasZoomIn').disabled=z>=48;
    hud(null);ovl();
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
    tabs.innerHTML='<div class="texture-tabs" id="textureTabs">'+h+'</div><button class="tab pvt'+(E.cur==='preview'?' on':'')+'" type="button" role="tab" aria-selected="'+(E.cur==='preview')+'" data-id="preview">'+ic('cube')+'<span>3D preview</span></button>';
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
      if(pv){await buildPreview();Motion.surface($('#edPv'))}
      else{
        $('#edEmpty').style.display='none';$('#edArea').style.display='';$('#edHud').style.display='';
        $('#edRight').classList.remove('off');var preferredZoom=d.zoom;redraw();setZoom(d.fitMode?fitZoom(d):preferredZoom||fitZoom(d));
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
  function textureColors(){
    var d=E.doc,root=$('#texturePalette');if(!d){root.innerHTML='';return}
    var r=viewRect(d),view=r.x+':'+r.y+':'+r.w+':'+r.h;
    if(d.paletteVersion!==d.version||d.paletteView!==view){
      var counts=new Map(),data=d.data.data;
      for(var y=r.y;y<r.y+r.h;y++)for(var x=r.x;x<r.x+r.w;x++){var i=(y*d.w+x)*4;if(data[i+3]){var key=data[i]+','+data[i+1]+','+data[i+2]+','+data[i+3];counts.set(key,(counts.get(key)||0)+1)}}
      d.palette=Array.from(counts.entries()).sort(function(a,b){return b[1]-a[1]}).map(function(item){return item[0].split(',').map(Number)});d.paletteVersion=d.version;d.paletteView=view;d.palettePage=0;
    }
    var page=d.palettePage||0,values=d.palette.slice(page*PALETTE_PAGE,(page+1)*PALETTE_PAGE);
    $('#textureColorCount').textContent='· '+d.palette.length;
    root.innerHTML=values.length?values.map(function(color){var hex='#'+hex2(color[0])+hex2(color[1])+hex2(color[2]),alpha=color[3]/255;return '<button class="texture-color" type="button" data-texture-color="'+hex+'" data-alpha="'+color[3]+'" aria-label="Use '+hex.toUpperCase()+' at '+Math.round(alpha*100)+'% opacity" title="'+hex.toUpperCase()+' · '+Math.round(alpha*100)+'%"><span style="background:rgba('+color.slice(0,3).join(',')+','+alpha+')"></span></button>'}).join(''):'<span class="mu" style="font-size:11px">No colors yet.</span>';
    var more=$('#texturePaletteMore');more.hidden=d.palette.length<=PALETTE_PAGE;more.textContent='More colors · '+(page+1)+' / '+Math.ceil(d.palette.length/PALETTE_PAGE);
  }
  function sync(){
    textureColors();
    $('#brushCustom').value=E.size;
    $$('.tb',$('#edTools')).forEach(function(b){b.setAttribute('aria-pressed',b.dataset.t===E.tool)});
    if(lastTool!==E.tool){$('#morePaintTools').open=!!$('#morePaintTools [data-t="'+E.tool+'"]');lastTool=E.tool;}
    $$('.sg',$('#edSize')).forEach(function(b){b.setAttribute('aria-pressed',+b.dataset.v===E.size)});
    $('#edCat').value=E.cat.split('/')[0];
    $$('.tg[data-e]',ed).forEach(function(b){b.setAttribute('aria-checked',String(!!E[b.dataset.e]))});
    $('#rowUV').style.display=E.p.type==='skin'?'':'none';
    var d=E.doc;$('#edRight').classList.toggle('off',!d||E.cur==='preview');$('#edUndo').disabled=!d||!d.undo.length;$('#edRedo').disabled=!d||!d.redo.length;
    var visible=!!d&&E.cur!=='preview';$('#canvasBar').hidden=!visible;$('#canvasFooter').hidden=!visible;
    var canSurface=!!d&&E.p.type!=='skin'&&window.TextureSurface.supported(d.data);
    if(!canSurface){E.depthEditing=false;ed.classList.remove('depth-editing');}
    $('#canvasSurface').hidden=!visible||!canSurface;$('#surfaceTools').hidden=!canSurface;
    $('#previewSurface').hidden=!canSurface||E.cur!=='preview';
    $('#canvasSurface').setAttribute('aria-pressed',String(E.depthEditing));$('#surfaceMode').setAttribute('aria-pressed',String(E.depthEditing));
    $('#surfaceMode span').textContent=E.depthEditing?'Back to colors':'Edit pixel depth';$('#depthControls').hidden=!E.depthEditing;
    $('#depthSelectionStatus').textContent=d&&d.selection?(d.selection.count===undefined?d.selection.w*d.selection.h:d.selection.count)+' pixels selected':'Select pixels or use the depth brush.';
    $$('[data-depth-adjust]').forEach(function(button){button.disabled=!d||!d.selection;});
    $$('[data-depth-tool]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.depthTool===E.tool));});
    $$('[data-depth-action]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.depthAction===E.depthAction));});
    $('#depthAmount').value=E.depthAmount;$('#depthAmountValue').textContent=E.depthAmount+'%';$('#depthValue').value=E.depthValue;$('#depthSoftness').value=E.depthSoftness;$('#depthView').value=E.depthView;
    $('#surfaceSummary').textContent=d&&d.surface?'Depth '+Math.round(d.surface.depth)+'% · Shine '+Math.round(d.surface.shine)+'%':'Give this texture height and shine.';
    if(d){var r=viewRect(d);$('#canvasTextureName').textContent=d.e.n||d.id.split('/').pop();$('#canvasDocumentMeta').textContent=E.depthEditing?'Editing pixel depth':d.layout?(d.frameView?'Editing frame '+(d.frame+1)+' of '+d.layout.steps.length:'Full animation sheet'):'Pixel canvas';}
    var help=E.hand?['Hand','Zoom in, then drag to move around. Click Hand again to paint.']:E.tool==='lasso'?['Lasso','Draw around the pixels to select. Then raise, lower, or set their height.']:TOOL_HELP[E.tool];
    if(E.depthEditing&&E.tool==='select')help=['Select depth','Drag to select pixels. Use the depth controls to raise, lower, or set height.'];
    if(E.depthEditing&&E.tool==='pencil')help=['Depth brush','Paint height inside the selection. Choose Raise, Lower, or Set height in the depth controls.'];
    $('#canvasToolName').textContent=help[0];$('#canvasToolHint').textContent=help[1];$('#toolGuide').textContent=help[1];
    $('#canvasPan').setAttribute('aria-pressed',String(!!E.hand));area.classList.toggle('hand-mode',!!E.hand);
    $('#canvasGrid').setAttribute('aria-pressed',String(!!E.grid));
    $$('#edTools .tb').forEach(function(b){var key={pencil:'B',eraser:'E',fill:'G',pick:'I',line:'L',rect:'R',ellipse:'O',select:'M',light:'U',dark:'D'}[b.dataset.t];b.title=TOOL_HELP[b.dataset.t][1]+' · '+key;b.setAttribute('aria-keyshortcuts',key)});
    $('#tintRow').hidden=!d||!MT.tintColor(d.e);$('#tintToggle').setAttribute('aria-checked',String(!!d&&d.viewTint));
    $('#edUndo').style.opacity=$('#edUndo').disabled?.4:1;$('#edRedo').style.opacity=$('#edRedo').disabled?.4:1;
    $('#edAlpha').value=E.alpha;
    animationControls.refresh();
    if(window.MobileEditor)window.MobileEditor.sync();
  }
  ed.addEventListener('click',function(e){
    var t=e.target,b;
    if(t.closest('#edBack')){close();return}
    if(E.loading)return;
    if(b=t.closest('[data-texture-color]')){setColor(b.dataset.textureColor);setAlpha(Number(b.dataset.alpha)/255*100);return}
    if(t.closest('#texturePaletteMore')&&E.doc){E.doc.palettePage=((E.doc.palettePage||0)+1)%Math.ceil(E.doc.palette.length/PALETTE_PAGE);textureColors();return}
    if(t.closest('#tintToggle')&&E.doc){var d=E.doc;d.viewTint=!d.viewTint;E.p.tintView=E.p.tintView||{};E.p.tintView[d.id]=d.viewTint;CB.save();redraw();sync();renderLeft();renderTabs();ovl();return}
    if(t.closest('#textureImport,#canvasImport')){importImage();return}
    if(t.closest('#mobileDepth')){if(E.depthEditing)openDepthPanel();else setDepthMode(true);return}
    if(t.closest('#canvasSurface,#surfaceMode')){setDepthMode(!E.depthEditing);return}
    if(b=t.closest('[data-depth-tool]')){if(drag)end();E.hand=false;E.tool=b.dataset.depthTool;if(innerWidth<=900)ed.classList.remove('r-open');sync();ovl();return}
    if(b=t.closest('[data-depth-adjust]')){adjustDepth(b.dataset.depthAdjust);return}
    if(b=t.closest('[data-depth-action]')){E.depthAction=b.dataset.depthAction;E.tool='pencil';sync();return}
    if(t.closest('[data-depth-deselect]')){selectionAction('none');return}
    if(t.closest('#surfaceOpen,#previewSurface')){if(drag)end();preview.stop();surfaceStudio.open();return}
    if(t.closest('#textureExport')){exportPNG();return}
    if(t.closest('#edDetails')){picker.close(false);CB.openDetails(E.p);return}
    if(t.closest('#edExport')){picker.close(false);window.ResourcePacks.exportProject(E.p);return}
    if(b=t.closest('#edL')){ed.classList.toggle('l-open');ed.classList.remove('r-open','frames-open');animationControls.layoutRail();return}
    if(b=t.closest('#edR')){var colors=ed.dataset.toolSection==='color';ed.dataset.toolSection='tools';ed.classList.toggle('r-open',colors||!ed.classList.contains('r-open'));ed.classList.remove('l-open','frames-open');animationControls.layoutRail();return}
    if(t.closest('#mobilePreview')){ed.classList.remove('l-open','r-open','frames-open');animationControls.layoutRail();activate(E.cur==='preview'?E.last||E.open[0]:'preview');return}
    if(t.closest('#edC')&&!t.closest('#canvasBar')&&(ed.classList.contains('l-open')||ed.classList.contains('r-open')||ed.classList.contains('frames-open'))){ed.classList.remove('l-open','r-open','frames-open');animationControls.layoutRail()}
    if(b=t.closest('#edTools .tb')){E.hand=false;E.tool=b.dataset.t;if(innerWidth<=900)ed.classList.remove('r-open');sync();ovl();return}
    if(t.closest('#canvasPan')){E.hand=!E.hand;sync();ovl();return}
    if(t.closest('#canvasGrid')){E.grid=!E.grid;setZoom(E.zoom);sync();return}
    if(t.closest('#canvasZoomIn')){setZoom(E.zoom*1.25,false);return}
    if(t.closest('#canvasZoomOut')){setZoom(E.zoom/1.25,false);return}
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
    if(t.closest('#edFit')){if(E.doc){setZoom(fitZoom(E.doc),true);area.scrollLeft=area.scrollTop=0;}return}
    if(t.closest('#edUndo')){undo();return}
    if(t.closest('#edRedo')){redo();return}
  });
  $('#edCat').innerHTML=MT.options();
  $('#edCat').addEventListener('change',function(){E.cat=this.value;E.page=0;renderLeft();persist()});
  $('#edZoom').addEventListener('input',function(){setZoom(+this.value,false)});
  $('#depthAmount').addEventListener('input',function(){E.depthAmount=Number(this.value);$('#depthAmountValue').textContent=E.depthAmount+'%';});
  $('#depthValue').addEventListener('input',function(){E.depthValue=Math.max(0,Math.min(100,Number(this.value)||0));});
  $('#depthSoftness').addEventListener('input',function(){E.depthSoftness=Number(this.value);});
  $('#depthView').addEventListener('change',function(){E.depthView=this.value;redraw();ovl();});
  $('#brushCustom').addEventListener('input',function(){E.size=Math.max(1,Math.min(32,Math.round(Number(this.value)||1)));ovl();});
  $('#brushCustom').addEventListener('change',sync);
  $('#texturePicker').addEventListener('change',function(){if(this.files[0])importImage(this.files[0]);this.value='';});
  $('#edAlpha').addEventListener('input',function(){setAlpha(+this.value)});
  $('#edHex').addEventListener('input',function(){var v=this.value.trim();if(v[0]!=='#')v='#'+v;if(/^#[0-9a-f]{6}$/i.test(v))setColor(v)});
  window.addEventListener('resize',function(){if(ed.classList.contains('show'))renderLeft()});
  function releaseSpaceHand(){if(spaceHand===null)return;endPan();E.hand=spaceHand;spaceHand=null;sync();ovl();}
  document.addEventListener('keyup',function(e){if(e.code==='Space'||e.key===' ')releaseSpaceHand()});
  window.addEventListener('blur',releaseSpaceHand);
  document.addEventListener('paste',function(e){
    if(e.defaultPrevented||!ed.classList.contains('show')||document.querySelector('dialog[open]')||$('#modal').classList.contains('show')||!picker.panel.hidden||e.target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])'))return;
    var files=e.clipboardData&&Array.from(e.clipboardData.files);if(files&&files.length===1){e.preventDefault();importImage(files[0]);}
  });
  document.addEventListener('keydown',function(e){
    if(!ed.classList.contains('show'))return;
    if(e.defaultPrevented||e.isComposing||document.querySelector('dialog[open]')||$('#modal').classList.contains('show')||!picker.panel.hidden||E.loading)return;
    var t=e.target,typing=t&&t.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"])');
    var mod=e.ctrlKey||e.metaKey,k=e.key.toLowerCase();
    if(typing)return;
    if(mod&&k==='s'){e.preventDefault();CB.save();window.LocalStore.flush();return}
    if(mod&&k==='z'){e.preventDefault();if(e.shiftKey)redo();else undo();return}
    if(mod&&k==='y'){e.preventDefault();redo();return}
    if(mod&&!e.altKey&&k==='f'){e.preventDefault();$('#edQ').focus();$('#edQ').select();return}
    if(mod&&e.shiftKey&&!e.altKey&&k==='i'){e.preventDefault();if(!e.repeat)importImage();return}
    if(mod&&k==='e'&&(e.shiftKey||e.altKey)){e.preventDefault();if(!e.repeat){if(e.altKey)exportPNG();else window.ResourcePacks.exportProject(E.p)}return}
    if(mod&&E.doc&&E.doc.layout&&!e.altKey&&(k==='d'||e.shiftKey&&(k==='c'||k==='x'||k==='v'))){
      e.preventDefault();if(!e.repeat)frameAction({d:'duplicate',c:'copy',x:'cut',v:'paste'}[k]);return;
    }
    if(mod&&e.shiftKey&&k==='a'){e.preventDefault();selectionAction('none');return}
    var actions={a:'all',c:'copy',x:'cut',v:'paste'};
    if(mod&&!e.altKey&&actions[k]){e.preventDefault();selectionAction(actions[k]);return}
    if(mod)return;
    if(e.altKey){
      if(k==='arrowleft'||k==='arrowright'){e.preventDefault();var tabs=E.open.concat('preview'),index=tabs.indexOf(E.cur);activate(tabs[(index+(k==='arrowright'?1:-1)+tabs.length)%tabs.length]);}
      return;
    }
    if(k==='escape'){if(E.doc&&E.doc.selection)selectionAction('none');else if(ed.classList.contains('l-open')||ed.classList.contains('r-open')||ed.classList.contains('frames-open')){ed.classList.remove('l-open','r-open','frames-open');animationControls.layoutRail()}else close();e.preventDefault();return}
    if(k==='delete'||k==='backspace'){e.preventDefault();if(E.doc&&E.doc.selection)selectionAction('clear');return}
    if(k==='?'){e.preventDefault();window.AppShell.help();return}
    if(k==='p'){e.preventDefault();if(!e.repeat){releaseSpaceHand();activate(E.cur==='preview'?(E.last||E.open[0]):'preview')}return}
    if(k==='w'&&e.shiftKey){e.preventDefault();if(!e.repeat)closeTab(E.cur);return}
    if(E.cur==='preview'){
      if(k==='f'||k==='0'){e.preventDefault();preview.reset();return}
      if(k==='+'||k==='='||k==='-'){e.preventDefault();preview.zoom=Math.max(.35,Math.min(3,preview.zoom*(k==='-'?1/1.15:1.15)));preview.transform();return}
      if(k.startsWith('arrow')){e.preventDefault();var step=e.shiftKey?15:5;if(k==='arrowleft')preview.ry-=step;if(k==='arrowright')preview.ry+=step;if(k==='arrowup')preview.rx=Math.min(89,preview.rx+step);if(k==='arrowdown')preview.rx=Math.max(-89,preview.rx-step);preview.transform();return}
      if(k===' '&&!t.closest('button')){e.preventDefault();if(!e.repeat){preview.auto=!preview.auto;preview.syncAuto()}return}
      return;
    }
    if(!E.doc)return;
    if(k===' '&&e.shiftKey&&E.doc.layout){e.preventDefault();if(!e.repeat){animationControls.setRailOpen(true);animationControls.playing?animationControls.stop():animationControls.play()}return}
    if(k===' '&&!t.closest('button')){e.preventDefault();if(spaceHand===null){if(drag)end();spaceHand=E.hand;E.hand=true;sync();ovl()}return}
    if(k==='f'&&e.shiftKey){e.preventDefault();if(!e.repeat&&!$('#edFramesToggle').hidden)$('#edFramesToggle').click();return}
    if(k==='a'&&e.shiftKey){e.preventDefault();if(!e.repeat){if(E.doc.layout)frameAction('duplicate');else if(!$('#canvasAnimate').hidden)$('#canvasAnimate').click()}return}
    if((k==='pageup'||k==='pagedown')&&E.doc.layout){e.preventDefault();selectAnimation(E.doc.frame+(k==='pageup'?-1:1),true);return}
    if(k==='g'&&e.shiftKey){e.preventDefault();if(!e.repeat)$('#canvasGrid').click();return}
    if(k==='h'){e.preventDefault();if(!e.repeat)$('#canvasPan').click();return}
    if(k==='f'){e.preventDefault();$('#edFit').click();return}
    if(k==='0'){e.preventDefault();setZoom(1,false);return}
    if(k==='c'){e.preventDefault();if(E.depthEditing)setDepthMode(false);picker.open();return}
    var map={b:'pencil',e:'eraser',g:'fill',i:'pick',l:'line',r:'rect',o:'ellipse',m:'select',u:'light',d:'dark'};
    if(map[k]){e.preventDefault();releaseSpaceHand();E.hand=false;E.tool=map[k];sync();ovl()}
    else if(k==='['){e.preventDefault();E.size=Math.max(1,E.size-1);sync();ovl()}
    else if(k===']'){e.preventDefault();E.size=Math.min(32,E.size+1);sync();ovl()}
    else if(k==='='||k==='+'){e.preventDefault();setZoom(E.zoom*1.15,false)}
    else if(k==='-'){e.preventDefault();setZoom(E.zoom/1.15,false)}
  });

  [
    ['edUndo','Control+Z Meta+Z','Undo · Ctrl / ⌘ Z'],
    ['edRedo','Control+Shift+Z Meta+Shift+Z Control+Y','Redo · Ctrl / ⌘ Shift Z'],
    ['edExport','Control+Shift+E Meta+Shift+E','Export project · Ctrl / ⌘ Shift E'],
    ['textureExport','Control+Alt+E Meta+Alt+E','Export texture PNG · Ctrl / ⌘ Alt E'],
    ['edQ','Control+F Meta+F','Search textures · Ctrl / ⌘ F'],
    ['edCol','C','Choose color · C'],['edFit','F','Fit canvas · F'],
    ['canvasPan','H','Hand tool · H; hold Space to pan temporarily'],
    ['canvasGrid','Shift+G','Pixel grid · Shift G'],
    ['canvasZoomIn','+ =','Zoom in · +'],['canvasZoomOut','-','Zoom out · −'],
    ['edFramesToggle','Shift+F','Show or hide frames · Shift F'],
    ['canvasAnimate','Shift+A','Create animation · Shift A'],
    ['animPlay','Space','Play / pause · Space in the frame panel; Shift Space on canvas'],
    ['animEarlier','Alt+ArrowUp','Move frame earlier · Alt ↑ in the frame panel'],
    ['animLater','Alt+ArrowDown','Move frame later · Alt ↓ in the frame panel'],
    ['pvReset','F 0','Reset 3D view · F / 0'],['pvAuto','Space','Toggle auto-rotation · Space in 3D'],
    ['canvasHelp','F1 Shift+Slash','Help and keyboard shortcuts · F1 / ?']
  ].forEach(function(item){var element=document.getElementById(item[0]);element.setAttribute('aria-keyshortcuts',item[1]);element.title=item[2];});
  $('#canvasImport').setAttribute('aria-keyshortcuts','Control+Shift+I Meta+Shift+I');

  /* ---------- open / close ---------- */
  async function readPNG(file){
    if(!file||file.size>16777216)throw new Error('Choose a PNG smaller than 16 MB.');
    var header=new Uint8Array(await file.slice(0,24).arrayBuffer());
    if(header.length<24||![137,80,78,71,13,10,26,10].every(function(value,index){return value===header[index]}))throw new Error('Choose a valid PNG image.');
    var size=new DataView(header.buffer),w=size.getUint32(16),h=size.getUint32(20);
    if(!w||!h||w*h>16777216)throw new Error('Choose a PNG with at most 16 million pixels.');
    var url=URL.createObjectURL(file),image=new Image();image.src=url;
    try{await image.decode();var canvas=document.createElement('canvas');canvas.width=image.width;canvas.height=image.height;var context=canvas.getContext('2d');context.drawImage(image,0,0);return context.getImageData(0,0,canvas.width,canvas.height)}
    finally{URL.revokeObjectURL(url)}
  }
  async function importImage(file){
    var d=E.doc,token=activeToken;if(!d||E.cur==='preview'||E.loading){CB.toast('Open a texture on the canvas first, then import your image.');return;}
    if(drag)end();picker.close(false);releaseSpaceHand();endPan();
    var version=d.version,project=E.p,frame=d.layout?TA.frameRect(d.layout,d.frame):null;
    try{
      var shared=d.layout?d.layout.steps.filter(function(step){return step.index===d.layout.steps[Math.min(d.frame,d.layout.steps.length-1)].index;}).length:1;
      var result=await ImageImporter.open({name:d.e.n||d.id,path:d.e.src,w:d.w,h:d.h,skin:E.p.type==='skin',animated:!!d.layout,frame:frame,frameNumber:d.frame,shared:shared,tintColor:MT.tintColor(d.e),viewTint:d.viewTint},file);
      if(!result)return;
      if(token!==activeToken||E.doc!==d||E.p!==project||d.version!==version){CB.toast('The open texture changed. Import the image again into the current texture.');return;}
      var image=result.data;
      if(E.p.type==='skin'&&(image.width!==64||image.height!==64))throw new Error('Skins need a 64×64 Minecraft layout.');
      if(d.layout){
        var r=result.scope==='frame'?frame:{x:0,y:0,w:d.w,h:d.h};
        if(image.width!==r.w||image.height!==r.h)throw new Error('Keep the current dimensions to preserve this animation.');
        var next=clone(d.data);for(var y=0;y<r.h;y++)next.data.set(image.data.subarray(y*r.w*4,(y+1)*r.w*4),((r.y+y)*d.w+r.x)*4);image=next;
      }
      pushUndo(d);d.data=image;d.depthLayer=null;d.selection=null;redraw();setZoom(fitZoom(d),true);ovl();
      var saved=await commit(d);
      if(saved)CB.toast(result.scope==='frame'?'Image applied to frame '+(d.frame+1)+'. Undo restores its pixels.':'Texture replaced. Image applied and saved locally. Undo restores the previous pixels.');
      else CB.toast('Image applied, but it could not be saved locally. Export a backup or retry saving.');
    }catch(error){CB.toast(error.message)}
  }
  async function exportPNG(){
    if(!E.doc)return;if(drag)end();var d=E.doc;
    try{var blob=await codec.png(clone(d.data));BenchArchive.download(blob,d.id.split('/').pop().replace(':','-')+'.png');CB.toast('Texture PNG downloaded.')}catch(error){CB.toast(error.message)}
  }
  function refreshDetails(){
    if(!E.p)return;
    $('#edName').textContent=E.p.name;$('#edDetails').hidden=E.p.type==='skin';$('#edPackLabel').textContent=E.p.type==='skin'?'Skin':'Texture pack';
    $('.local-note',ed).textContent=E.p.type==='skin'?'Autosaves on this device · export a PNG':'Autosaves on this device · export a ZIP to share';
    $('#edExport').setAttribute('aria-label',E.p.type==='skin'?'Export skin PNG':'Export Minecraft resource pack ZIP');$('#edExport').title=E.p.type==='skin'?'Export skin PNG':'Export resource pack ZIP';renderPal();
  }
  async function open(p){
    await CB.ready;
    endPan();E.hand=false;
    lastTool=null;$$('#edRight details').forEach(function(details){details.open=false});
    if(drag)end();
    var token=++activeToken;surfaceStudio.close(false);preview.stop();picker.close(false);ImageImporter.close();animationControls.stop();
    if(packSession){packSession.release();packSession=null;}
    E.depthEditing=false;ed.classList.remove('depth-editing');E.loading=true;E.doc=null;E.catalog=MT;$('#edQ').disabled=true;
    E.p=p;p.edits=p.edits||{};E.docs={};E.pending={};BC={};E.faceModel=null;E.open=[];E.cur=null;E.last=null;E.q='';E.page=0;E.tool='pencil';E.size=1;E.mx=E.my=false;E.alpha=100;E.grid=D.set.grid!==false;hover=null;animationControls.refresh();
    $('#edName').textContent=p.name;$('#edPath').textContent='';$('#edArea').style.display='none';$('#edPv').classList.remove('on');$('#edRight').classList.add('off');
    $('#edEmpty').style.display='flex';$('#edEmpty b').textContent='Opening local project…';$('#edEmpty span').textContent='';
    ed.classList.remove('l-open','r-open','frames-open');ed.classList.add('show');document.body.style.overflow='hidden';Motion.editor(ed);
    if(window.EditorLayout)window.EditorLayout.fit();
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
    releaseSpaceHand();endPan();E.hand=false;
    if(drag)end();activeToken++;surfaceStudio.close(false);preview.stop();picker.close(false);ImageImporter.close();animationControls.stop();
    if(E.p&&!E.loading)persist();
    ed.classList.remove('show','l-open','r-open','frames-open');document.body.style.overflow='';
    $('#app>.main').inert=false;$('#app>.sb').inert=false;
    if(packSession){packSession.release();packSession=null;}
    E.doc=null;E.p=null;E.loading=false;E.docs={};E.pending={};BC={};E.catalog=MT;drag=null;CB.save();CB.renderAll();
  }
  window.Ed={open:open,close:close,enterDepth:function(){return setDepthMode(true)},exitDepth:function(){if(E.depthEditing)return setDepthMode(false)},refreshDetails:refreshDetails,readPNG:readPNG,importImage:importImage,replacePNG:importImage,exportPNG:exportPNG,selectionAction:selectionAction,refreshLayout:function(light){if(E.p&&!E.loading&&ed.classList.contains('show')){if(!light)renderLeft();if(E.cur==='preview')preview.transform();else fitViewport()}},prepareExport:function(){if(drag)end();CB.save()}};
})();
