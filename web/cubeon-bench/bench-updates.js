(function () {
  'use strict';
  var release='pixel-depth-v1',storageKey='cb-bench-update',seen=false,ready=false,showing=false,queued=false;
  function hasSeen(){
    if(seen||window.CB.D.set.lastBenchNotice===release)return true;
    try{return localStorage.getItem(storageKey)===release;}catch(_){return false;}
  }
  function available(){return document.body.classList.contains('inapp')&&!document.querySelector('dialog[open]')&&
    !document.getElementById('modal').classList.contains('show')&&!document.getElementById('ed').classList.contains('show');}
  function remember(){seen=true;window.CB.D.set.lastBenchNotice=release;try{localStorage.setItem(storageKey,release);}catch(_){}window.CB.save();}
  async function show(manual){
    if(showing||!ready||!manual&&(hasSeen()||!available()))return;
    showing=true;
    try{
      var answer=window.AppDialog.open({title:'New: edit texture depth',accept:'Try depth editing',cancel:'Got it',html:
        '<div class="bench-update-art" aria-hidden="true"><span></span><span></span><span></span></div>'+
        '<p>Give selected pixels height and shine. Your texture colors stay unchanged.</p>'+
        '<ol><li>Open a texture and choose Depth.</li><li>Select pixels with a rectangle or lasso.</li><li>Raise, lower, or set the height. Use a soft depth brush for finer details.</li></ol>'+
        '<p>Surface settings includes presets, height-map import, and a 3D preview. Pack export includes your shader maps automatically.</p>'+
        '<p class="mu">Minecraft needs LabPBR-compatible shaders with parallax/POM enabled for visible depth.</p>'});
      if(document.getElementById('appDialog').open)remember();
      if(await answer){
        var project=window.CB.D.projects.filter(function(p){return p.type==='pack';}).sort(function(a,b){return b.edited-a.edited;})[0];
        if(project){await window.Ed.open(project);await window.Ed.enterDepth();}
        else window.CB.newProject({type:'pack'});
      }
    }catch(error){window.CB.toast(error.message);}
    finally{showing=false;}
  }
  function queue(){if(queued||!ready||hasSeen())return;queued=true;requestAnimationFrame(function(){queued=false;show(false);});}
  window.CB.ready.then(function(){ready=true;queue();},function(){});
  document.addEventListener('cb-render',queue);document.addEventListener('close',queue,true);
  new MutationObserver(queue).observe(document.body,{attributes:true,attributeFilter:['class']});
  new MutationObserver(queue).observe(document.getElementById('modal'),{attributes:true,attributeFilter:['class']});
  document.getElementById('benchWhatsNew').addEventListener('click',function(){show(true);});
  window.addEventListener('storage',function(event){if(event.key===storageKey&&event.newValue===release)seen=true;});
  window.BenchUpdates={show:function(){show(true)},release:release,hasSeen:hasSeen};
})();
