(function () {
  'use strict';
  var TS=window.TextureSurface, codec=window.TextureCodec, three;
  function canvas(image) {
    var cv=document.createElement('canvas');cv.width=image.width;cv.height=image.height;
    cv.getContext('2d').putImageData(image,0,0);return cv;
  }
  function SurfacePreview(host, interactive) {
    this.host=host;this.canvas=document.createElement('canvas');this.canvas.className='surface-3d-canvas';
    this.canvas.setAttribute('aria-label','3D surface preview');this.canvas.tabIndex=interactive?0:-1;
    if(!interactive)this.canvas.style.pointerEvents='none';
    host.appendChild(this.canvas);this.rx=-22;this.ry=-35;this.zoom=1;this.disposed=false;this.raf=0;
    var self=this,pointer=null;
    if(interactive) {
      this.canvas.addEventListener('pointerdown',function(e){if(e.button>0||pointer)return;pointer={id:e.pointerId,x:e.clientX,y:e.clientY};self.canvas.setPointerCapture(e.pointerId);});
      this.canvas.addEventListener('pointermove',function(e){if(!pointer||pointer.id!==e.pointerId)return;self.rotate(self.rx-(e.clientY-pointer.y)*.5,self.ry+(e.clientX-pointer.x)*.5,self.zoom);pointer.x=e.clientX;pointer.y=e.clientY;});
      ['pointerup','pointercancel','lostpointercapture'].forEach(function(name){self.canvas.addEventListener(name,function(){pointer=null;});});
      this.canvas.addEventListener('wheel',function(e){e.preventDefault();self.rotate(self.rx,self.ry,self.zoom*(e.deltaY<0?1.08:.92));},{passive:false});
    }
    if(!three)three=import('./vendor/three.module.min.js');
    this.ready=three.then(function(T){
      if(self.disposed)return;
      self.T=T;self.renderer=new T.WebGLRenderer({canvas:self.canvas,alpha:true,antialias:true,powerPreference:'low-power'});
      self.renderer.setPixelRatio(Math.min(devicePixelRatio||1,1.5));self.renderer.setClearColor(0,0);
      self.renderer.outputColorSpace=T.SRGBColorSpace;self.renderer.toneMapping=T.ACESFilmicToneMapping;
      self.scene=new T.Scene();self.camera=new T.PerspectiveCamera(35,1,.1,50);
      self.scene.add(new T.HemisphereLight(0xffffff,0x566051,2));
      var key=new T.DirectionalLight(0xffffff,3);key.position.set(-3,4,5);self.scene.add(key);
      var fill=new T.DirectionalLight(0xd9e5ff,1.5);fill.position.set(4,-2,3);self.scene.add(fill);
      var faces=Array.from({length:6},function(_,index){
        var cv=document.createElement('canvas');cv.width=cv.height=64;var ctx=cv.getContext('2d');
        var gradient=ctx.createLinearGradient(0,0,64,64);gradient.addColorStop(0,index===2?'#ffffff':'#b5c3ba');gradient.addColorStop(.45,'#ecf2ed');gradient.addColorStop(1,'#53615b');
        ctx.fillStyle=gradient;ctx.fillRect(0,0,64,64);return cv;
      });
      self.environment=new T.CubeTexture(faces);self.environment.colorSpace=T.SRGBColorSpace;self.environment.needsUpdate=true;self.scene.environment=self.environment;
      self.group=new T.Group();self.scene.add(self.group);
      self.textures=[0,1,2].map(function(){
        var texture=new T.CanvasTexture(document.createElement('canvas'));texture.magFilter=T.NearestFilter;
        texture.minFilter=T.NearestFilter;texture.generateMipmaps=false;texture.wrapS=texture.wrapT=T.RepeatWrapping;return texture;
      });
      self.textures[0].colorSpace=T.SRGBColorSpace;
      self.material=new T.MeshStandardMaterial({map:self.textures[0],displacementMap:self.textures[1],normalMap:self.textures[2],
        displacementScale:.35,displacementBias:-.35,roughness:.85,metalness:0,side:T.DoubleSide,transparent:true,alphaTest:.02});
      self.backMaterial=new T.MeshStandardMaterial({color:0x687466,roughness:.8});
      self.observer=new ResizeObserver(function(){self.render();});self.observer.observe(host);
      self.render();
    });
    this.ready.catch(function(){});
  }
  SurfacePreview.prototype.set=async function(image,maps,options,frame){
    await this.ready;if(this.disposed)return;
    this.sources=[canvas(image),canvas(maps.height),canvas(maps.normalRGB)];
    this.opaque=true;for(var i=3;i<image.data.length;i+=4)if(image.data[i]<255){this.opaque=false;break;}
    this.frameKey=null;this.material.roughness=Math.max(.04,1-options.shine/100);this.material.metalness=options.metal?1:0;
    this.frame(frame||{x:0,y:0,w:image.width,h:image.height,index:0});
    if(this.back)this.back.visible=this.opaque;
  };
  SurfacePreview.prototype.frame=function(frame){
    if(!this.sources||this.disposed)return;
    var key=[frame.x,frame.y,frame.w,frame.h,frame.step,Math.round((frame.mix||0)*20)].join(':');
    if(key===this.frameKey)return;this.frameKey=key;
    for(var i=0;i<3;i++){
      var cv=this.textures[i].image;cv.width=frame.w;cv.height=frame.h;var ctx=cv.getContext('2d');ctx.imageSmoothingEnabled=false;
      window.TextureAnimation.paintFrame(ctx,this.sources[i],frame,0,0,frame.w,frame.h);this.textures[i].needsUpdate=true;
    }
    var dimensions=frame.w+':'+frame.h;
    if(this.dimensions!==dimensions){
      this.dimensions=dimensions;
      if(this.mesh){this.mesh.geometry.dispose();this.group.remove(this.mesh);this.back.geometry.dispose();this.group.remove(this.back);}
      var unit=2/Math.max(frame.w,frame.h),w=frame.w*unit,h=frame.h*unit,T=this.T;
      this.mesh=new T.Mesh(new T.PlaneGeometry(w,h,Math.max(2,Math.min(128,frame.w*2)),Math.max(2,Math.min(128,frame.h*2))),this.material);
      this.back=new T.Mesh(new T.BoxGeometry(w,h,.04),this.backMaterial);this.back.position.z=-.38;this.group.add(this.back,this.mesh);
      this.back.visible=this.opaque;
    }
    this.render();
  };
  SurfacePreview.prototype.rotate=function(rx,ry,zoom){
    rx=Math.max(-85,Math.min(85,rx));zoom=Math.max(.4,Math.min(2.8,zoom));
    if(this.rx===rx&&this.ry===ry&&this.zoom===zoom&&this.drawn)return;
    this.rx=rx;this.ry=ry;this.zoom=zoom;this.render();
  };
  SurfacePreview.prototype.render=function(){
    if(this.disposed||!this.renderer||this.raf)return;var self=this;
    this.raf=requestAnimationFrame(function(){
      self.raf=0;if(self.disposed)return;
      var w=self.host.clientWidth,h=self.host.clientHeight;if(!w||!h)return;
      if(self.renderWidth!==w||self.renderHeight!==h){
        self.renderWidth=w;self.renderHeight=h;self.renderer.setSize(w,h,false);self.camera.aspect=w/h;self.camera.updateProjectionMatrix();
      }
      self.camera.position.z=Math.max(4.2,4.2/self.camera.aspect)/self.zoom;
      self.group.rotation.set(self.rx*Math.PI/180,self.ry*Math.PI/180,0);
      self.renderer.render(self.scene,self.camera);self.drawn=true;
    });
  };
  SurfacePreview.prototype.dispose=function(){
    if(this.disposed)return;
    this.disposed=true;cancelAnimationFrame(this.raf);if(this.observer)this.observer.disconnect();
    if(this.mesh)this.mesh.geometry.dispose();if(this.back)this.back.geometry.dispose();
    if(this.material)this.material.dispose();if(this.backMaterial)this.backMaterial.dispose();
    if(this.textures)this.textures.forEach(function(texture){texture.dispose();});
    if(this.environment)this.environment.dispose();
    if(this.renderer){this.renderer.dispose();this.renderer.forceContextLoss();}
    this.sources=null;this.canvas.remove();
  };
  SurfacePreview.displayImage=function(doc){
    var image=new ImageData(new Uint8ClampedArray(doc.data.data),doc.w,doc.h),color=window.MinecraftTextures.tintColor(doc.e);
    return color&&doc.viewTint!==false?window.MinecraftTextures.tintImage(image,color):image;
  };
  function Studio(options){
    this.options=options;this.host=document.getElementById('surfaceStudio');this.opened=false;this.token=0;this.frameRaf=0;
    this.$=function(id){return document.getElementById(id);};var self=this;
    this.host.addEventListener('click',function(event){
      var target=event.target,button=target.closest('[data-surface-preset]');
      if(target.closest('[data-surface-close]')){self.close();return;}
      if(button){
        var presets={soft:{depth:25,shine:10,smooth:1,metal:false},raised:{depth:55,shine:15,smooth:0,metal:false},metal:{depth:35,shine:80,smooth:0,metal:true}};
        Object.assign(self.draft,presets[button.dataset.surfacePreset]);self.controls();self.update();return;
      }
      if(target.closest('#surfaceApply'))self.apply();
      if(target.closest('#surfaceRemove'))self.apply(true);
      if(target.closest('#surfaceImportHeight')){self.$('surfaceHeightPicker').value='';self.$('surfaceHeightPicker').click();}
      if(target.closest('#surfaceResetHeight')){self.working=null;delete self.draft.height;self.draft.invert=false;self.lastPaint=null;self.controls();self.update();}
      if(target.closest('#surfaceDownload'))self.download();
      if(target.closest('#surfaceUndoPaint'))self.undoPaint();
      if(button=target.closest('[data-surface-brush]')){self.brush=button.dataset.surfaceBrush;self.controls();}
      if(button=target.closest('[data-surface-view]')){
        var map=button.dataset.surfaceView==='height';self.$('surfaceMapView').hidden=!map;self.$('surfaceScene').hidden=map;
        self.host.querySelectorAll('[data-surface-view]').forEach(function(b){b.setAttribute('aria-pressed',String(b===button));});
        if(!map&&self.view)self.view.render();if(map)self.fitMap();
      }
    });
    this.host.addEventListener('input',function(event){
      var key={surfaceDepth:'depth',surfaceShine:'shine',surfaceSmooth:'smooth',surfaceInvert:'invert',surfaceMetal:'metal'}[event.target.id];
      if(key){self.draft[key]=event.target.type==='checkbox'?event.target.checked:Number(event.target.value);self.controls();self.update();}
    });
    this.$('surfaceHeightPicker').addEventListener('change',async function(){
      if(!this.files[0]||!self.opened)return;var token=self.token;
      try{
        var image=await TS.readPNG(this.files[0]);if(token!==self.token)return;
        self.working=image;delete self.draft.height;self.draft.invert=false;self.lastPaint=null;
        self.$('surfaceStatus').textContent='Height map loaded. It will fit this texture.';self.controls();self.update();
      }catch(error){if(token===self.token)self.$('surfaceStatus').textContent=error.message;}
    });
    var painting=null,cv=this.$('surfaceHeightCanvas');
    cv.addEventListener('pointerdown',function(event){
      if(!self.opened||!self.maps||event.button>0||painting)return;
      if(!self.working||self.working.width!==self.image.width||self.working.height!==self.image.height||self.draft.invert||self.draft.smooth){
        self.working=new ImageData(new Uint8ClampedArray(self.maps.base.data),self.image.width,self.image.height);
        delete self.draft.height;self.draft.invert=false;self.draft.smooth=0;self.controls();
      }
      self.lastPaint=new ImageData(new Uint8ClampedArray(self.working.data),self.working.width,self.working.height);
      painting={id:event.pointerId,last:self.point(event)};cv.setPointerCapture(event.pointerId);self.paint(painting.last,painting.last);
    });
    cv.addEventListener('pointermove',function(event){if(painting&&painting.id===event.pointerId){var point=self.point(event);self.paint(painting.last,point);painting.last=point;}});
    ['pointerup','pointercancel','lostpointercapture'].forEach(function(name){cv.addEventListener(name,function(){painting=null;self.controls();});});
    this.cancelPaint=function(){if(painting){var pointer=painting.id;painting=null;if(cv.hasPointerCapture(pointer))cv.releasePointerCapture(pointer);}};
    this.mapObserver=new ResizeObserver(function(){self.fitMap();});this.mapObserver.observe(this.$('surfaceHeightStage'));
    document.addEventListener('keydown',function(event){
      if(!self.opened)return;event.stopImmediatePropagation();
      if(event.key==='Escape'){event.preventDefault();self.close();}
      else if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='z'){event.preventDefault();self.undoPaint();}
      else if(event.key==='Tab'){
        var focusable=Array.from(self.host.querySelectorAll('button:not(:disabled),input:not([type=file]),select:not(:disabled),canvas[tabindex="0"]')).filter(function(el){return !el.closest('[hidden]')&&el.getClientRects().length;});
        if(!focusable.length)return;var first=focusable[0],last=focusable[focusable.length-1];
        if(event.shiftKey&&document.activeElement===first){event.preventDefault();last.focus();}
        else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first.focus();}
      } else if(self.view&&document.activeElement===self.view.canvas&&/^Arrow/.test(event.key)){
        event.preventDefault();self.view.rotate(self.view.rx+(event.key==='ArrowUp'?-5:event.key==='ArrowDown'?5:0),self.view.ry+(event.key==='ArrowLeft'?-5:event.key==='ArrowRight'?5:0),self.view.zoom);
      }
    },true);
  }
  Studio.prototype.controls=function(){
    var self=this;
    ['Depth','Shine','Smooth'].forEach(function(name){self.$('surface'+name).value=self.draft[name.toLowerCase()];self.$('surface'+name+'Value').textContent=name==='Smooth'?['Crisp','Soft','Softer'][self.draft.smooth]:Math.round(self.draft[name.toLowerCase()])+'%';});
    this.$('surfaceInvert').checked=this.draft.invert;this.$('surfaceMetal').checked=this.draft.metal;
    this.$('surfaceUndoPaint').disabled=!this.lastPaint;this.$('surfaceResetHeight').hidden=!this.working&&!this.draft.height;
    this.$('surfaceHeightSource').textContent=this.working||this.draft.height?'Custom height map':'Generated from the texture';
    this.host.querySelectorAll('[data-surface-brush]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.surfaceBrush===self.brush));});
  };
  Studio.prototype.open=function(){
    if(this.opened)return;
    var doc=this.options.read();if(!doc||doc.id==='skin'||!TS.supported(doc.data))return;
    this.doc=doc;this.image=new ImageData(new Uint8ClampedArray(doc.data.data),doc.w,doc.h);
    this.displayImage=SurfacePreview.displayImage(doc);
    this.draft=TS.settings(doc.surface)||{version:1,depth:40,shine:15,smooth:0,invert:false,metal:false};
    this.working=null;this.lastPaint=null;this.brush='raise';this.rect=this.options.rect();this.returnFocus=document.activeElement;
    this.opened=true;this.token++;this.host.hidden=false;document.getElementById('ed').inert=true;
    this.$('surfaceTitle').textContent=doc.surface?'Edit texture depth':'Add texture depth';
    this.$('surfaceTextureLabel').textContent=doc.e.n+(doc.layout?' · Frame '+(doc.frame+1):'');this.$('surfaceRemove').hidden=!doc.surface;
    this.$('surfaceStatus').textContent='';this.$('surfaceMapView').hidden=true;this.$('surfaceScene').hidden=false;
    this.host.querySelectorAll('[data-surface-view]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.surfaceView==='3d'));});
    this.view=new SurfacePreview(this.$('surfaceScene'),true);this.controls();this.update();this.$('surfaceDepth').focus({preventScroll:true});
  };
  Studio.prototype.update=function(){
    if(this.frameRaf||!this.opened)return;var self=this,token=this.token;
    this.frameRaf=requestAnimationFrame(async function(){
      self.frameRaf=0;if(token!==self.token||!self.opened)return;
      try{
        self.maps=TS.generate(self.image,self.draft,self.doc.e,self.working);
        var cv=self.$('surfaceHeightCanvas'),r=self.rect;cv.width=r.w;cv.height=r.h;
        var source=canvas(self.maps.base),ctx=cv.getContext('2d');ctx.imageSmoothingEnabled=false;ctx.drawImage(source,r.x,r.y,r.w,r.h,0,0,r.w,r.h);
        self.fitMap();
      }catch(error){
        if(token!==self.token)return;
        self.maps=null;self.$('surfaceStatus').textContent=error.message;return;
      }
      try{await self.view.set(self.displayImage,self.maps,self.draft,r);}
      catch(error){
        if(token!==self.token)return;
        self.$('surfaceStatus').textContent='3D preview unavailable. You can still edit and save the maps.';
        self.$('surfaceMapView').hidden=false;self.$('surfaceScene').hidden=true;
        self.host.querySelectorAll('[data-surface-view]').forEach(function(button){button.setAttribute('aria-pressed',String(button.dataset.surfaceView==='height'));});
        self.fitMap();
      }
    });
  };
  Studio.prototype.fitMap=function(){
    if(!this.opened||!this.rect)return;
    var stage=this.$('surfaceHeightStage'),w=stage.clientWidth,h=stage.clientHeight;if(!w||!h)return;
    var scale=Math.min((w-8)/this.rect.w,(h-8)/this.rect.h),cv=this.$('surfaceHeightCanvas');
    cv.style.width=Math.max(1,this.rect.w*scale)+'px';cv.style.height=Math.max(1,this.rect.h*scale)+'px';
  };
  Studio.prototype.point=function(event){
    var rect=this.$('surfaceHeightCanvas').getBoundingClientRect(),r=this.rect;
    return [r.x+Math.max(0,Math.min(r.w-1,Math.floor((event.clientX-rect.left)/rect.width*r.w))),r.y+Math.max(0,Math.min(r.h-1,Math.floor((event.clientY-rect.top)/rect.height*r.h)))];
  };
  Studio.prototype.paint=function(from,to){
    var steps=Math.max(Math.abs(to[0]-from[0]),Math.abs(to[1]-from[1]),1),size=Number(this.$('surfaceBrushSize').value),r=this.rect,level=this.brush==='raise'?255:0;
    for(var step=0;step<=steps;step++){
      var px=Math.round(from[0]+(to[0]-from[0])*step/steps),py=Math.round(from[1]+(to[1]-from[1])*step/steps),offset=(size-1)>>1;
      for(var dy=0;dy<size;dy++)for(var dx=0;dx<size;dx++){
        var x=px+dx-offset,y=py+dy-offset;if(x<r.x||y<r.y||x>=r.x+r.w||y>=r.y+r.h)continue;
        this.working.data.set([level,level,level,255],(y*this.working.width+x)*4);
      }
    }
    this.update();
  };
  Studio.prototype.undoPaint=function(){if(!this.lastPaint)return;this.working=this.lastPaint;this.lastPaint=null;this.controls();this.update();};
  Studio.prototype.saved=function(){var result=Object.assign({},this.draft);if(this.working)result.height=codec.encode(this.working);return TS.settings(result);};
  Studio.prototype.apply=async function(remove){
    if(this.$('surfaceApply').disabled)return;this.$('surfaceApply').disabled=true;this.$('surfaceRemove').disabled=true;
    try{
      var ok=await this.options.apply(remove?null:this.saved());
      if(ok===false)this.$('surfaceStatus').textContent='Saving failed. Try again or export a backup.';
      else this.close();
    }catch(error){this.$('surfaceStatus').textContent=error.message;}
    finally{this.$('surfaceApply').disabled=false;this.$('surfaceRemove').disabled=false;}
  };
  Studio.prototype.download=async function(){
    this.$('surfaceDownload').disabled=true;
    try{
      var maps=TS.generate(this.image,this.saved(),this.doc.e),name=(this.doc.e.textureId||this.doc.id).split('/').pop(),files=Object.create(null);
      for(var item of [['height',maps.height],['normal',maps.normalRGB],['n',maps.normal],['s',maps.material]])files[name+'_'+item[0]+'.png']=new Uint8Array(await TS.png(item[1]).arrayBuffer());
      files['Read me.txt']=new TextEncoder().encode('Cubeon Bench texture maps\n\n'+name+'_height.png: grayscale height reference.\n'+name+'_normal.png: standard RGB normal map.\n'+name+'_n.png and '+name+'_s.png: LabPBR shader maps. Place beside the original texture in a Minecraft Java resource pack.\n\nA compatible shader pack is required for surface shading; parallax/POM support must be enabled for visible depth. Normal Minecraft keeps the original flat texture.\n');
      window.BenchArchive.download(await window.BenchArchive.write(files),name+' depth maps.zip');
    }catch(error){this.$('surfaceStatus').textContent=error.message;}
    finally{this.$('surfaceDownload').disabled=false;}
  };
  Studio.prototype.close=function(resume){
    if(!this.opened)return;this.opened=false;this.token++;cancelAnimationFrame(this.frameRaf);this.frameRaf=0;
    this.cancelPaint();if(this.view)this.view.dispose();this.view=null;this.host.hidden=true;document.getElementById('ed').inert=false;
    this.image=this.displayImage=this.working=this.lastPaint=this.maps=null;
    if(resume!==false){if(this.returnFocus&&this.returnFocus.isConnected)this.returnFocus.focus({preventScroll:true});if(this.options.closed)this.options.closed();}
  };
  window.SurfacePreview=SurfacePreview;window.SurfaceStudio=Studio;
})();
