/* Cubeon v2 "Overworld": generated pixel textures, hill scene, depth meter. */
(function(){
  var root=document.documentElement;
  function rnd(seed){var s=seed;return function(){s=(s*1664525+1013904223)>>>0;return s/4294967296}}
  /* 16px transparent speckle tile, shown at 4x so each speck is a chunky pixel */
  function tile(size,seed,dark,light,ore){
    var c=document.createElement('canvas');c.width=c.height=size;var g=c.getContext('2d'),r=rnd(seed),x,y,n;
    for(y=0;y<size;y++)for(x=0;x<size;x++){n=r();
      if(n<dark){g.fillStyle='rgba(0,0,0,.22)';g.fillRect(x,y,1,1)}
      else if(n>1-light){g.fillStyle='rgba(255,255,255,.07)';g.fillRect(x,y,1,1)}}
    if(ore){for(n=0;n<ore.count;n++){var ox=Math.floor(r()*(size-3)),oy=Math.floor(r()*(size-3));
      g.fillStyle=ore.color;[[1,0],[0,1],[1,1],[2,1],[1,2]].forEach(function(p){g.fillRect(ox+p[0],oy+p[1],1,1)});
      g.fillStyle='#fff';g.fillRect(ox+1,oy+1,1,1)}}
    return 'url('+c.toDataURL()+')'}
  try{
    root.style.setProperty('--tex-dirt',tile(16,7,.13,.09));
    root.style.setProperty('--tex-stone',tile(16,21,.1,.12));
    root.style.setProperty('--tex-deep',tile(16,33,.16,.05));
    root.style.setProperty('--tex-ore',tile(48,5,.12,.04,{count:1,color:'#3FD6D0'}));
  }catch(e){}
  /* make the textures crisp when scaled */
  var st=document.createElement('style');st.textContent='.strip,.section,.cta{image-rendering:pixelated}';document.head.appendChild(st);

  /* depth meter: 64 at the surface down to -58 at the bottom */
  var d=document.createElement('div');d.className='depth';d.setAttribute('aria-hidden','true');d.innerHTML='Y <b>64</b>';document.body.appendChild(d);
  var yEl=d.querySelector('b'),nav=document.querySelector('.navbar'),hasSky=root.classList.contains('sky');
  function onScroll(){
    var max=Math.max(1,document.documentElement.scrollHeight-innerHeight),p=Math.min(1,scrollY/max);
    yEl.textContent=Math.round(64-p*122);
    if(nav&&hasSky)nav.classList.toggle('top',scrollY<24)}
  addEventListener('scroll',onScroll,{passive:true});onScroll();

  /* count the hero FPS number up once; skipped for reduced motion */
  var fn=document.getElementById('fpsNum');
  if(fn&&!matchMedia('(prefers-reduced-motion: reduce)').matches){var t0=null,to=206;
    (function tick(t){if(t0===null)t0=t;var k=Math.min(1,(t-t0)/1800),e=1-Math.pow(1-k,3);fn.textContent=Math.round(to*e);if(k<1)requestAnimationFrame(tick)})(performance.now())}

  /* hills: three stepped layers drawn on a tiny canvas, scaled up crisp */
  var cv=document.getElementById('hills');if(!cv)return;
  var PX=5,H=44;
  function draw(){
    var w=Math.ceil(innerWidth/PX)+2;cv.width=w;cv.height=H;
    cv.style.height=(H*PX)+'px';
    var g=cv.getContext('2d');g.clearRect(0,0,w,H);
    var L=[{b:22,a:6,f:.03,p:1.3,top:'#A4DCA0',body:'#86C98A'},
           {b:28,a:6,f:.055,p:4,top:'#62C24A',body:'#4EAA36'},
           {b:34,a:4,f:.09,p:2,top:'#4CB637',dirt:1}];
    L.forEach(function(l,i){var r=rnd(100+i);
      for(var x=0;x<w;x++){
        var y=Math.round(l.b+l.a*(Math.sin(x*l.f+l.p)+.5*Math.sin(x*l.f*2.3+l.p*2)));
        g.fillStyle=l.top;g.fillRect(x,y,1,l.dirt?3:1);
        if(l.dirt){g.fillStyle='#3E8F2C';g.fillRect(x,y+2,1,1);
          for(var yy=y+3;yy<H;yy++){var n=r();g.fillStyle=n<.12?'#5E3A1C':n>.93?'#8F5C30':'#6B4020';g.fillRect(x,yy,1,1)}}
        else{g.fillStyle=l.body;g.fillRect(x,y+1,1,H-y-1)}}});
    /* a few blocky trees on the middle hill */
    var t=rnd(9);for(var k=0;k<Math.floor(w/26);k++){var tx=Math.floor(4+k*26+t()*12),ty=Math.round(28+6*(Math.sin(tx*.055+4)+.5*Math.sin(tx*.055*2.3+8)));
      g.fillStyle='#6B4020';g.fillRect(tx,ty-5,1,5);g.fillStyle='#2F8F2A';g.fillRect(tx-2,ty-9,5,4);g.fillStyle='#3FA836';g.fillRect(tx-1,ty-11,3,2)}
    var tint={sunrise:'rgba(255,150,130,.22)',sunset:'rgba(150,50,90,.30)',night:'rgba(4,8,40,.62)'}[(window.__tod||{}).phase];
    if(tint){g.globalCompositeOperation='source-atop';g.fillStyle=tint;g.fillRect(0,0,w,H);g.globalCompositeOperation='source-over'}
  }
  /* sun / moon travels an arc with the visitor's clock; rises from behind the hills */
  var hero=cv.parentNode,sun=hero.querySelector('.sun'),T=window.__tod;
  function place(){if(!sun||!T)return;var h=T.h,p=T.phase==='night'?((h-18+24)%24)/12:(h-6)/13,
    W=hero.clientWidth,Hh=hero.clientHeight,sz=sun.offsetWidth,hor=Hh-cv.offsetHeight*.78,top=Math.max(108,hor*.12);
    sun.style.left=(W*(.04+.92*p)-sz/2)+'px';sun.style.top=(hor-Math.sin(Math.PI*p)*(hor-top)-sz/2)+'px'}
  /* stars (night only) */
  if(T){var st=document.createElement('div');st.className='stars';st.setAttribute('aria-hidden','true');
    var r=rnd(77),html='';for(var i=0;i<70;i++)html+='<i style="left:'+(r()*100).toFixed(1)+'%;top:'+(r()*100).toFixed(1)+'%"></i>';
    st.innerHTML=html;hero.insertBefore(st,hero.firstChild)}
  /* live clock: re-place the sun/moon and swap the sky when the phase changes
     (not when ?time= / ?hour= is forcing a preview) */
  var forced=/[?&](time|hour)=/.test(location.search);
  function tick(){if(forced||!T)return;var n=new Date(),h=n.getHours()+n.getMinutes()/60,
    ph=(h<5||h>=20)?'night':h<8?'sunrise':h<17?'day':'sunset',ch=ph!==T.phase;T.h=h;T.phase=ph;
    if(ch){root.dataset.tod=ph;draw()}place()}
  setInterval(tick,30000);document.addEventListener('visibilitychange',function(){if(!document.hidden)tick()});
  if(sun)sun.style.transition='left 2s linear,top 2s linear';
  draw();place();var rt;addEventListener('resize',function(){clearTimeout(rt);rt=setTimeout(function(){draw();place()},120)});
})();
