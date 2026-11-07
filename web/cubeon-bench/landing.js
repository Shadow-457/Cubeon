(function () {
  'use strict';
  var reduced = matchMedia('(prefers-reduced-motion: reduce)'), art = document.getElementById('heroArt');
  var themeButton=document.getElementById('landingTheme');
  function applyTheme(theme,persist){
    var dark=theme==='dark';document.documentElement.dataset.theme=theme;
    themeButton.setAttribute('aria-pressed',String(dark));themeButton.setAttribute('aria-label',dark?'Switch to light theme':'Switch to dark theme');themeButton.querySelector('use').setAttribute('href',dark?'#sun':'#moon');
    document.querySelector('meta[name="theme-color"]').content=dark?'#111414':'#f6f7f2';
    document.querySelectorAll('[data-dark-src]').forEach(function(img){img.src=dark?img.dataset.darkSrc:img.dataset.lightSrc;});
    if(persist)try{localStorage.setItem('bench-landing-theme',theme);}catch(_){}
    window.dispatchEvent(new CustomEvent('benchlandingtheme',{detail:theme}));
  }
  themeButton.addEventListener('click',function(){applyTheme(document.documentElement.dataset.theme==='dark'?'light':'dark',true);});
  applyTheme(document.documentElement.dataset.theme||'light',false);
  var flowRaf=0;
  function flow(){
    flowRaf=0;
    var nodes=document.querySelectorAll('.workspace-section,.feature,.local-section,.creative-marquee,.final-invitation');
    var measurements=Array.from(nodes).map(function(node){return {node:node,rect:node.getBoundingClientRect()};});
    measurements.forEach(function(item){
      var node=item.node,r=item.rect,enter=reduced.matches?1:Math.max(0,Math.min(1,(innerHeight-r.top)/(innerHeight*.8))),travel=reduced.matches ? .5 : Math.max(0,Math.min(1,(innerHeight-r.top)/(innerHeight+r.height)));
      node.style.setProperty('--flow-enter',enter.toFixed(4));
      node.style.setProperty('--demo-tilt',((1-enter)*12).toFixed(3)+'deg');node.style.setProperty('--demo-scale',(.91+enter*.09).toFixed(4));
      node.style.setProperty('--tile-spread',((1-enter)*37).toFixed(3)+'px');node.style.setProperty('--texture-turn',(-18+travel*36).toFixed(3)+'deg');
      node.style.setProperty('--flower-turn',(reduced.matches?0:Math.floor(travel*8)*45)+'deg');node.style.setProperty('--skin-turn',(-30+travel*70).toFixed(3)+'deg');
      node.style.setProperty('--mark-offset',((1-enter)*130).toFixed(2));node.style.setProperty('--marquee-x',(-travel*350).toFixed(2)+'px');
      node.style.setProperty('--invite-y',((1-enter)*45).toFixed(2)+'px');
      if(node.querySelector('.animation-art'))node.dataset.currentFrame=String(Math.min(4,Math.floor(travel*5)));
    });
  }
  function queueFlow(){if(!flowRaf)flowRaf=requestAnimationFrame(flow);}
  window.addEventListener('scroll',queueFlow,{passive:true});window.addEventListener('resize',queueFlow);reduced.addEventListener('change',queueFlow);queueFlow();
  document.querySelectorAll('.faq-list details').forEach(function(details){
    var animation=null,wanted=details.open,answer=details.querySelector('p');
    details.querySelector('summary').addEventListener('click',function(event){
      if(reduced.matches||!answer.animate)return;
      event.preventDefault();if(!animation)wanted=details.open;wanted=!wanted;
      var from=details.open?answer.getBoundingClientRect().height:0;if(animation)animation.cancel();details.open=true;
      answer.style.overflow='hidden';var to=wanted?answer.scrollHeight:0;
      animation=answer.animate([{height:from+'px',opacity:from?1:0},{height:to+'px',opacity:wanted?1:0}],{duration:350,easing:'cubic-bezier(.22,1,.36,1)'});
      var current=animation;current.finished.then(function(){if(animation===current){details.open=wanted;answer.style.overflow='';animation=null;}}).catch(function(){});
    });
  });
  if ('IntersectionObserver' in window) {
    document.body.classList.add('enhanced');
    var reveal = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {if (entry.isIntersecting) {entry.target.classList.add('visible');reveal.unobserve(entry.target);}});
    }, {threshold:.08});
    document.querySelectorAll('.reveal').forEach(function (element) {reveal.observe(element);});
  }
  var captions = {
    draw:'Pick a color. Put down a pixel. See where it takes you.',
    animate:'A few frames, a little timing, and your idea comes to life.',
    preview:'Turn it around. See your work in its own little world.'
  };
  function selectDemo(button) {
    document.querySelectorAll('[data-demo]').forEach(function (tab) {
      var selected = tab === button;
      tab.setAttribute('aria-selected', String(selected));tab.tabIndex = selected ? 0 : -1;
      document.getElementById('panel-' + tab.dataset.demo).hidden = !selected;
    });
    document.getElementById('demoCaption').textContent = captions[button.dataset.demo];
    var panel = document.getElementById('panel-' + button.dataset.demo);
    if (!reduced.matches && panel.animate) panel.animate([{opacity:.3,transform:'translateY(5px)'},{opacity:1,transform:'none'}], {duration:380,easing:'cubic-bezier(.22,1,.36,1)'});
  }
  document.querySelectorAll('[data-demo]').forEach(function (button) {
    button.addEventListener('click', function () {selectDemo(button);});
    button.addEventListener('keydown', function (event) {
      var tabs = Array.from(document.querySelectorAll('[data-demo]')), index = tabs.indexOf(button);
      if (event.key === 'ArrowRight') index = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') index = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') index = 0;
      else if (event.key === 'End') index = tabs.length - 1;
      else return;
      event.preventDefault();selectDemo(tabs[index]);tabs[index].focus();
    });
  });
  var paletteName = 'meadow';
  function paletteSelection(button) {
    paletteName = button.dataset.palette;
    document.querySelectorAll('[data-palette]').forEach(function (other) {other.setAttribute('aria-pressed', String(other === button));});
    art.dataset.palette = paletteName;
    document.getElementById('sceneHint').textContent = button.title + ' palette. Make it your own.';
  }
  document.querySelectorAll('[data-palette]').forEach(function (button) {button.addEventListener('click', function () {paletteSelection(button);});});
  if ('serviceWorker' in navigator && location.protocol !== 'file:' && window.isSecureContext) navigator.serviceWorker.register('sw.js', {scope:'./',updateViaCache:'none'}).catch(function () {});

  // A pinned local Three.js build drives one reversible scroll sequence.
  import('./vendor/three.module.min.js').then(function (THREE) {
    var canvas=document.getElementById('heroScene'), renderer;
    try{renderer=new THREE.WebGLRenderer({canvas:canvas,alpha:true,antialias:true,preserveDrawingBuffer:true,powerPreference:'low-power'});}
    catch(_){canvas.dataset.renderer='fallback';return;}
    renderer.setPixelRatio(Math.min(devicePixelRatio||1,innerWidth<760?1.5:1.75));
    renderer.setClearColor(0,0);renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=1.15;
    var scene=new THREE.Scene(),camera=new THREE.OrthographicCamera(-3,3,3,-3,.1,30);
    camera.position.set(0,.4,7);camera.lookAt(0,0,0);
    var ambient=new THREE.HemisphereLight(0xffffff,0xc5d2b2,2);scene.add(ambient);
    var sun=new THREE.DirectionalLight(0xfff8e9,3);sun.position.set(-4,7,5);sun.castShadow=true;sun.shadow.mapSize.set(1024,1024);sun.shadow.camera.left=-6;sun.shadow.camera.right=6;sun.shadow.camera.top=6;sun.shadow.camera.bottom=-6;sun.shadow.normalBias=.03;scene.add(sun);
    var rim=new THREE.DirectionalLight(0xc9e2d9,0);rim.position.set(4,2,-3);scene.add(rim);
    function lightScene(){
      var dark=document.documentElement.dataset.theme==='dark';
      ambient.color.set(dark?0xe9eef4:0xffffff);ambient.groundColor.set(dark?0x7b8490:0xc5d2b2);ambient.intensity=dark?1.55:2;
      sun.color.set(dark?0xffffff:0xfff8e9);sun.intensity=dark?2.4:3;rim.intensity=dark?1.4:0;
      renderer.toneMappingExposure=dark?1.05:1.15;
    }
    lightScene();
    var world=new THREE.Group();scene.add(world);
    var palettes={meadow:{petal:'#cc935b',center:'#f1cf79',stem:'#628347'},stone:{petal:'#7395a8',center:'#c8d6d9',stem:'#4a6970'},ember:{petal:'#c86e50',center:'#efb881',stem:'#777044'}};
    var slots=[0,-1,1,-2,2],cards=[],pixels=[];
    for(var y=0;y<16;y++)for(var x=0;x<16;x++){
      var dx=Math.abs(x-8),dy=Math.abs(y-5),kind=null;
      if(x===8&&y>=7)kind='stem';
      if(y===10&&x>=5&&x<=8||y===12&&x>=8&&x<=11)kind='stem';
      if(dx<=1&&dy<=3||dx<=3&&dy<=1)kind='petal';
      if(dx<=1&&dy<=1)kind='center';
      if(kind)pixels.push({x:x,y:y,kind:kind});
    }
    pixels.sort(function(a,b){return b.y-a.y||a.x-b.x;});
    function paintTile(tile,progress,phase){
      var ctx=tile.getContext('2d'),palette=palettes[paletteName],size=20;
      ctx.clearRect(0,0,320,320);
      var dark=document.documentElement.dataset.theme==='dark';
      for(var y=0;y<16;y++)for(var x=0;x<16;x++){ctx.fillStyle=dark?((x+y)%2?'#29302d':'#242a27'):((x+y)%2?'#eef1e6':'#e5ead9');ctx.fillRect(x*size,y*size,size,size);}
      pixels.slice(0,Math.floor(progress*pixels.length)).forEach(function(pixel){
        var dx=pixel.kind==='petal'&&pixel.y<5?Math.round(Math.sin(phase)*.65):0;
        ctx.fillStyle=palette[pixel.kind];ctx.fillRect((pixel.x+dx)*size,pixel.y*size,size,size);
      });
      ctx.strokeStyle=dark?'#a8b4ac14':'#a6b59335';ctx.lineWidth=1;
      for(var n=1;n<16;n++){ctx.beginPath();ctx.moveTo(n*size,0);ctx.lineTo(n*size,320);ctx.stroke();ctx.beginPath();ctx.moveTo(0,n*size);ctx.lineTo(320,n*size);ctx.stroke();}
    }
    var boardGeometry=new THREE.BoxGeometry(3.24,3.24,.065),faceGeometry=new THREE.PlaneGeometry(3.12,3.12);
    for(var i=0;i<5;i++){
      var tile=document.createElement('canvas');tile.width=tile.height=320;paintTile(tile,1,i);
      var texture=new THREE.CanvasTexture(tile);texture.colorSpace=THREE.SRGBColorSpace;texture.magFilter=THREE.NearestFilter;
      var frame=new THREE.Group(),back=new THREE.Mesh(boardGeometry,new THREE.MeshStandardMaterial({color:0xffffff,roughness:.8,transparent:true}));back.castShadow=true;back.receiveShadow=true;frame.add(back);
      var front=new THREE.Mesh(faceGeometry,new THREE.MeshStandardMaterial({map:texture,roughness:.9,transparent:true}));front.position.z=.035;frame.add(front);world.add(frame);
      cards.push({group:frame,back:back,front:front,tile:tile,texture:texture,key:''});
    }
    var cursorCanvas=document.createElement('canvas');cursorCanvas.width=cursorCanvas.height=64;
    var cc=cursorCanvas.getContext('2d');cc.fillStyle='#fff';cc.strokeStyle='#33452b';cc.lineWidth=2;cc.beginPath();cc.moveTo(14,6);cc.lineTo(14,48);cc.lineTo(26,37);cc.lineTo(35,57);cc.lineTo(43,53);cc.lineTo(34,34);cc.lineTo(51,32);cc.closePath();cc.fill();cc.stroke();
    var cursor=new THREE.Sprite(new THREE.SpriteMaterial({map:new THREE.CanvasTexture(cursorCanvas),transparent:true,depthTest:false}));cursor.scale.set(.44,.44,1);cards[0].group.add(cursor);
    var flower=new THREE.Group();world.add(flower);
    function extrude(points,depth,color){var shape=new THREE.Shape();points.forEach(function(p,i){if(i)shape.lineTo(p[0],p[1]);else shape.moveTo(p[0],p[1]);});shape.closePath();var mesh=new THREE.Mesh(new THREE.ExtrudeGeometry(shape,{depth:depth,bevelEnabled:false}),new THREE.MeshStandardMaterial({color:color,roughness:.53,transparent:true}));mesh.castShadow=true;mesh.receiveShadow=true;flower.add(mesh);return mesh;}
    var petal=extrude([[-.3,.7],[-.3,1.12],[.3,1.12],[.3,.7],[.72,.7],[.72,.1],[.3,.1],[.3,-.32],[-.3,-.32],[-.3,.1],[-.72,.1],[-.72,.7]],.14,palettes.meadow.petal);
    var center=extrude([[-.22,.2],[.22,.2],[.22,.64],[-.22,.64]],.17,palettes.meadow.center);center.position.z=.025;
    var stem=extrude([[-.075,-.3],[.075,-.3],[.075,-1.42],[-.075,-1.42]],.09,palettes.meadow.stem);
    var leaf1=extrude([[0,-.6],[-.45,-.6],[-.45,-.43],[-.12,-.43],[-.12,-.51],[0,-.51]],.09,palettes.meadow.stem);
    var leaf2=extrude([[0,-.99],[.45,-.99],[.45,-.83],[.12,-.83],[.12,-.91],[0,-.91]],.09,palettes.meadow.stem);
    flower.scale.setScalar(1.4);
    var shadow=new THREE.Mesh(new THREE.PlaneGeometry(15,15),new THREE.ShadowMaterial({opacity:.1}));shadow.rotation.x=-Math.PI/2;shadow.position.y=-2.1;shadow.receiveShadow=true;scene.add(shadow);
    var scrollHost=document.getElementById('heroScroll'),paused=false,active=true,raf=0,previous=performance.now(),progress=0,targetProgress=0,angle=.0,targetAngle=.0,pointer=null,chapter=-1;
    var clamp=function(v){return Math.max(0,Math.min(1,v));},smooth=function(v){v=clamp(v);return v*v*(3-2*v);},lerp=function(a,b,t){return a+(b-a)*t;};
    var chapters=[
      {title:'Small pixels.<br><span>Big possibilities.</span>',description:'A new look for the world you love. Draw textures, bring them to life, and make a skin that feels like you.',label:'The first pixel is yours.',count:'01 / Draw your idea'},
      {title:'Make it move.<br><span>Frame by frame.</span>',description:'A little change. Another frame. Watch a still texture become something with a life of its own.',label:'One idea. A few frames. A little magic.',count:'02 / Give it a little life'},
      {title:'Made by you.<br><span>Into your world.</span>',description:'From a few pixels to something that feels like you. Preview it, export it, and bring it into Minecraft.',label:'A few pixels. Something entirely yours.',count:'03 / Make it yours'}
    ];
    function setChapter(next){
      if(next===chapter)return;chapter=next;canvas.dataset.stage=String(next);
      var info=chapters[next],title=document.getElementById('hero-title'),description=document.querySelector('.hero-description');
      title.innerHTML=info.title;description.textContent=info.description;document.getElementById('artStageLabel').textContent=info.label;document.getElementById('scrollStageCount').textContent=info.count;
      document.querySelectorAll('[data-chapter]').forEach(function(el){el.classList.toggle('active',Number(el.dataset.chapter)===next);});
      if(!reduced.matches&&title.animate){title.animate([{opacity:0,transform:'translateY(12px)'},{opacity:1,transform:'none'}],{duration:500,easing:'cubic-bezier(.22,1,.36,1)'});description.animate([{opacity:0},{opacity:1}],{duration:650});}
    }
    function readProgress(){targetProgress=reduced.matches?0:clamp((scrollY-scrollHost.offsetTop)/Math.max(1,scrollHost.offsetHeight-innerHeight));document.getElementById('scrollProgress').style.transform='scaleX('+targetProgress+')';schedule();}
    function resize(){var width=art.clientWidth,height=art.clientHeight,view=innerWidth<760?2.05:2.85;renderer.setSize(width,height,false);camera.left=-view*width/height;camera.right=view*width/height;camera.top=view;camera.bottom=-view;camera.updateProjectionMatrix();readProgress();}
    function render(now){
      raf=0;if(!active||document.hidden)return;
      var delta=Math.min(.05,(now-previous)/1000);previous=now;
      progress+= (targetProgress-progress)*(reduced.matches?1:Math.min(1,delta*9));angle+=(targetAngle-angle)*(reduced.matches?1:Math.min(1,delta*9));
      var fan=smooth((progress-.22)/.3),finish=smooth((progress-.63)/.25),paint=reduced.matches?1:lerp(.65,1,clamp(progress/.26));
      setChapter(progress<.3?0:progress<.68?1:2);
      camera.zoom=lerp(1.06,.72,fan)*(1+finish*.24);camera.position.x=Math.sin(progress*Math.PI)*.65;camera.lookAt(0,0,0);camera.updateProjectionMatrix();world.rotation.y=angle;
      cards.forEach(function(card,i){
        var slot=slots[i],opacity=(i===0?1:lerp(.9,1,fan))*(1-finish),scale=lerp(1,.68,fan)*(1-finish*.25);
        card.group.position.set(lerp(-i*.085,slot*1.02,fan)+slot*finish*.6,lerp(i*.055,Math.abs(slot)*.18,fan)+finish*.8,lerp(-i*.16,-Math.abs(slot)*.3,fan)-finish*1.3);
        card.group.rotation.set(lerp(-.12,.03,fan),lerp(-.3,slot*-.15,fan),lerp(-.04,slot*-.08,fan));card.group.scale.setScalar(scale);card.group.visible=opacity>.005;
        card.back.material.opacity=card.front.material.opacity=opacity;card.back.material.color.set(document.documentElement.dataset.theme==='dark'?0x657067:0xffffff);
        var phase=i+(paused||reduced.matches?0:now*.003),key=document.documentElement.dataset.theme+':'+paletteName+':'+(i===0?Math.floor(paint*pixels.length):pixels.length)+':'+Math.round(Math.sin(phase)*.65);
        if(key!==card.key){paintTile(card.tile,i===0?paint:1,phase);card.texture.needsUpdate=true;card.key=key;}
      });
      var last=pixels[Math.min(pixels.length-1,Math.floor(paint*pixels.length))];cursor.position.set((last.x-7.5)*3.12/16,(7.5-last.y)*3.12/16,.14);cursor.visible=progress<.29&&!reduced.matches;
      flower.visible=finish>.005;flower.scale.setScalar(1.4*finish);flower.rotation.set(.03,lerp(-.8,.35,finish),Math.sin(progress*2)*.06);flower.position.y=finish*.1;
      [[petal,'petal'],[center,'center'],[stem,'stem'],[leaf1,'stem'],[leaf2,'stem']].forEach(function(item){item[0].material.color.set(palettes[paletteName][item[1]]);item[0].material.opacity=finish;});
      renderer.render(scene,camera);canvas.dataset.renderer='three';canvas.dataset.progress=progress.toFixed(3);art.classList.add('scene-ready');
      if(!reduced.matches&&(!paused||Math.abs(targetProgress-progress)>.0002||Math.abs(targetAngle-angle)>.0002))raf=requestAnimationFrame(render);
    }
    function schedule(){if(!raf&&active&&!document.hidden)raf=requestAnimationFrame(render);}
    window.addEventListener('scroll',readProgress,{passive:true});
    window.addEventListener('benchlandingtheme',function(){lightScene();schedule();});
    canvas.addEventListener('pointerdown',function(event){if(event.button!==0)return;pointer={id:event.pointerId,x:event.clientX};canvas.setPointerCapture(event.pointerId);canvas.focus({preventScroll:true});});
    canvas.addEventListener('pointermove',function(event){if(pointer&&pointer.id===event.pointerId){targetAngle+=(event.clientX-pointer.x)*.008;pointer.x=event.clientX;schedule();}});
    ['pointerup','pointercancel','lostpointercapture'].forEach(function(name){canvas.addEventListener(name,function(){pointer=null;});});
    canvas.addEventListener('keydown',function(event){if(event.key==='ArrowLeft'||event.key==='ArrowUp')targetAngle-=.15;else if(event.key==='ArrowRight'||event.key==='ArrowDown')targetAngle+=.15;else return;event.preventDefault();schedule();});
    document.querySelectorAll('[data-palette]').forEach(function(button){button.addEventListener('click',schedule);});
    var pauseButton=document.getElementById('scenePause');pauseButton.hidden=false;
    pauseButton.addEventListener('click',function(){paused=!paused;pauseButton.setAttribute('aria-pressed',String(paused));pauseButton.setAttribute('aria-label',paused?'Resume preview animation':'Pause preview animation');if(raf){cancelAnimationFrame(raf);raf=0;}schedule();});
    reduced.addEventListener('change',function(){if(raf){cancelAnimationFrame(raf);raf=0;}readProgress();resize();});
    document.addEventListener('visibilitychange',function(){previous=performance.now();if(document.hidden){cancelAnimationFrame(raf);raf=0;}else schedule();});
    window.addEventListener('pagehide',function(){cancelAnimationFrame(raf);raf=0;});window.addEventListener('pageshow',readProgress);
    canvas.addEventListener('webglcontextlost',function(event){event.preventDefault();cancelAnimationFrame(raf);raf=0;active=false;art.classList.remove('scene-ready');canvas.dataset.renderer='fallback';pauseButton.hidden=true;});
    if('IntersectionObserver' in window)new IntersectionObserver(function(entries){active=entries[0].isIntersecting;if(active){previous=performance.now();readProgress();}else{cancelAnimationFrame(raf);raf=0;}},{threshold:0}).observe(art);
    if('ResizeObserver' in window)new ResizeObserver(resize).observe(art);else window.addEventListener('resize',resize);
    resize();readProgress();schedule();
  }).catch(function(){document.getElementById('heroScene').dataset.renderer='fallback';});
})();
