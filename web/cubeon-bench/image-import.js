(function () {
  'use strict';
  var MAX_BYTES=16777216,MAX_PIXELS=16777216,current=null;
  function dimensions(bytes,kind){
    var v=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength),w=0,h=0;
    if(kind==='png'&&bytes.length>=24){
      w=v.getUint32(16);h=v.getUint32(20);
      for(var offset=8;offset+12<=bytes.length;){
        var chunkLength=v.getUint32(offset),chunkName=String.fromCharCode.apply(null,bytes.subarray(offset+4,offset+8));
        if(chunkName==='acTL')throw new Error('Choose a still image. Import animation frames one at a time.');
        if(chunkName==='IDAT'||offset+chunkLength+12>bytes.length)break;offset+=chunkLength+12;
      }
    }
    if(kind==='webp'&&bytes.length>=30){
      var chunk=String.fromCharCode.apply(null,bytes.subarray(12,16));
      if(chunk==='VP8X'){
        if(bytes[20]&2)throw new Error('Choose a still image. Import animation frames one at a time.');
        w=1+bytes[24]+(bytes[25]<<8)+(bytes[26]<<16);h=1+bytes[27]+(bytes[28]<<8)+(bytes[29]<<16);
      }else if(chunk==='VP8 '&&bytes[23]===157&&bytes[24]===1&&bytes[25]===42){w=v.getUint16(26,true)&16383;h=v.getUint16(28,true)&16383;}
      else if(chunk==='VP8L'&&bytes[20]===47){w=1+((bytes[22]&63)<<8)+bytes[21];h=1+((bytes[24]&15)<<10)+(bytes[23]<<2)+(bytes[22]>>6);}
    }
    if(kind==='jpeg'){
      for(var i=2;i+8<bytes.length;){
        if(bytes[i++]!==255)break;
        while(bytes[i]===255)i++;
        var marker=bytes[i++];if(marker===217||marker===218)break;
        if(marker===1||marker>=208&&marker<=215)continue;
        if(i+2>bytes.length)break;var length=v.getUint16(i);if(length<2||i+length>bytes.length)break;
        if([192,193,194,195,197,198,199,201,202,203,205,206,207].includes(marker)){h=v.getUint16(i+3);w=v.getUint16(i+5);break;}
        i+=length;
      }
    }
    if(!w||!h)throw new Error('Choose a valid PNG, JPG, or WebP image.');
    if(w*h>MAX_PIXELS||w>16384||h>16384)throw new Error('Choose an image with at most 16 million pixels and no side larger than 16,384 pixels.');
  }
  async function read(file){
    if(!file||!file.size)throw new Error('This file is empty. Choose a PNG, JPG, or WebP image.');
    if(file.size>MAX_BYTES)throw new Error('Choose an image smaller than 16 MB.');
    var bytes=new Uint8Array(await file.arrayBuffer()),kind;
    if([137,80,78,71,13,10,26,10].every(function(n,i){return bytes[i]===n;}))kind='png';
    else if(bytes[0]===255&&bytes[1]===216&&bytes[2]===255)kind='jpeg';
    else if(String.fromCharCode.apply(null,bytes.subarray(0,4))==='RIFF'&&String.fromCharCode.apply(null,bytes.subarray(8,12))==='WEBP')kind='webp';
    else throw new Error('This isn’t a PNG, JPG, or WebP image. Choose a supported image file.');
    dimensions(bytes,kind);
    var url=URL.createObjectURL(new Blob([bytes],{type:'image/'+kind})),img=new Image();
    try{
      img.src=url;await img.decode();
      if(!img.naturalWidth||!img.naturalHeight||img.naturalWidth*img.naturalHeight>MAX_PIXELS||Math.max(img.naturalWidth,img.naturalHeight)>16384)throw new Error('Choose a smaller image with at most 16 million pixels.');
      var cv=document.createElement('canvas');cv.width=img.naturalWidth;cv.height=img.naturalHeight;cv.getContext('2d').drawImage(img,0,0);
      return {canvas:cv,kind:kind};
    }catch(error){if(error.message.startsWith('Choose'))throw error;throw new Error('This image could not be read. Try exporting it as a PNG or JPG.');}
    finally{URL.revokeObjectURL(url);img.src='';}
  }
  function icon(path){return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+path+'</svg>';}
  function sampling(canvas,kind){
    if(kind==='jpeg')return 'smooth';
    var sample=document.createElement('canvas');sample.width=Math.min(64,canvas.width);sample.height=Math.min(64,canvas.height);
    var ctx=sample.getContext('2d');ctx.imageSmoothingEnabled=false;ctx.drawImage(canvas,0,0,sample.width,sample.height);
    var data=ctx.getImageData(0,0,sample.width,sample.height).data,colors=new Set();
    for(var i=0;i<data.length;i+=4){colors.add(data[i]+','+data[i+1]+','+data[i+2]+','+data[i+3]);if(colors.size>256)return 'smooth';}
    return 'pixel';
  }
  var upload=icon('<path d="M12 16V4m-4 4 4-4 4 4M4 16v4h16v-4"/>');
  var picture=icon('<rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8" cy="8" r="1.5"/><path d="m3 17 6-6 4 4 3-3 5 5"/>');
  function open(target,file){
    if(current)current.cancel();
    var previous=document.activeElement,host=document.createElement('dialog');host.id='imageImport';host.className='image-import';host.setAttribute('aria-labelledby','imageImportTitle');
    host.innerHTML='<header class="import-header"><div><h2 id="imageImportTitle">Import image</h2><p>Crop and resize an image for the selected texture.</p></div><button class="import-icon" id="importClose" type="button" aria-label="Close image import">'+icon('<path d="m6 6 12 12M18 6 6 18"/>')+'</button></header>'+
      '<div class="import-destination"><span>'+picture+'</span><div><b id="importDestination"></b><small id="importDestinationMeta"></small></div><span class="import-local">On your device</span></div>'+
      '<div class="import-content"><section class="import-source"><div class="import-section-label"><h3>01 <span>Source image</span></h3><button type="button" id="importChange" class="import-text" hidden>Change image</button></div>'+
      '<input id="importFile" type="file" accept="image/png,image/jpeg,image/webp,.png,.jpg,.jpeg,.webp" hidden><button type="button" id="importDrop" class="import-drop">'+upload+'<b>Drop an image here</b><span>or browse your files</span><small>PNG, JPG, WebP · up to 16 MB<br>You can also paste an image</small></button>'+
      '<div id="importSourceWrap" class="import-source-wrap" hidden><canvas id="importSourceCanvas" tabindex="0" role="img" aria-label="Source image and crop. Drag to position, or use arrow keys." aria-describedby="importCropHint"></canvas></div>'+
      '<div class="import-file-info" id="importFileInfo" hidden><b id="importFileName"></b><span id="importFileMeta"></span></div><p id="importCropHint" class="import-hint" hidden>Drag to move the crop. Arrow keys fine-tune it.</p></section>'+
      '<section class="import-result"><div class="import-section-label"><h3>02 <span>Texture preview</span></h3><output id="importOutputSize"></output></div><div class="import-preview" id="importPreview" data-backdrop="auto"><div class="import-preview-empty">'+picture+'<span>Choose an image to preview</span></div><div class="import-texture-frame" id="importTextureFrame" hidden><canvas id="importOutput" hidden aria-label="Exact texture preview"></canvas><canvas id="importTintOutput" hidden aria-label="Texture preview with Minecraft tint"></canvas></div></div>'+
      '<div class="import-preview-footer"><label><input type="checkbox" id="importGrid"> Pixel grid</label><label id="importTintRow" hidden title="Preview Minecraft tint without changing image pixels"><input type="checkbox" id="importTint"> Game tint</label><span id="importPixelCount">Preview before you apply</span></div><label class="import-backdrop" for="importBackdrop" title="For viewing only; your image pixels stay unchanged"><span>Preview backdrop</span><select id="importBackdrop"><option value="auto">Auto</option><option value="light">Light</option><option value="dark">Dark</option></select></label><p class="import-hint" id="importTintHint" hidden>Minecraft tints this texture in game. Your original image colors are saved.</p></section>'+
      '<aside class="import-controls"><div class="import-section-label"><h3>03 <span>Texture settings</span></h3></div><fieldset id="importOptions" disabled>'+
      '<div id="importScopeRow" class="import-field" hidden><label for="importScope">Apply to</label><select id="importScope"><option value="frame">Selected frame</option><option value="sheet">Entire sheet</option></select><p id="importScopeHint"></p></div>'+
      '<div class="import-field"><label for="importResolution">Texture size</label><select id="importResolution"></select><p id="importResolutionHint"></p></div>'+
      '<div class="import-field"><span class="import-label" id="importFitLabel">Image fit</span><div class="import-segmented" role="group" aria-labelledby="importFitLabel"><button type="button" data-fit="cover" aria-pressed="true">Fill</button><button type="button" data-fit="contain" aria-pressed="false">Fit</button><button type="button" data-fit="stretch" aria-pressed="false">Stretch</button></div><p id="importFitHint">Fill the texture; crop the edges.</p></div>'+
      '<div class="import-field" id="importZoomRow"><label for="importZoom">Crop zoom <output id="importZoomValue">100%</output></label><input type="range" id="importZoom" min="100" max="400" value="100" step="1"><button type="button" class="import-text" id="importReset">Reset crop</button></div>'+
      '<div class="import-transforms" role="group" aria-label="Image orientation"><button type="button" id="importRotate">'+icon('<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>')+'Rotate</button><button type="button" id="importFlip" aria-pressed="false">'+icon('<path d="M12 3v18M3 7v10l6-5-6-5Zm18 0v10l-6-5 6-5Z"/>')+'Flip</button></div>'+
      '<details class="import-details"><summary>Resizing and transparency</summary><div class="import-field"><label for="importSampling">Resampling</label><select id="importSampling"><option value="pixel">Sharp pixels</option><option value="smooth">Smooth image</option></select><p>Sharp preserves pixel art. Smooth works well for photos.</p></div>'+
      '<div class="import-field"><label for="importBackground">Background</label><select id="importBackground"><option value="transparent">Keep transparency</option><option value="solid">Solid color</option></select><label class="import-color" id="importColorRow" hidden><input type="color" id="importColor" value="#ffffff">Background color</label></div></details></fieldset></aside></div>'+
      '<div class="import-feedback" id="importFeedback" role="status" aria-live="polite" hidden></div><footer class="import-footer"><p id="importApplyHint">Your texture stays as it is until you apply.</p><div><button type="button" class="import-secondary" id="importCancel">Cancel</button><button type="button" class="import-primary" id="importApply" disabled>Apply image '+icon('<path d="M5 12h14m-5-5 5 5-5 5"/>')+'</button></div></footer>';
    document.body.appendChild(host);
    var $=function(id){return host.querySelector('#'+id);},resolve,source=null,oriented=null,output=null,fit='cover',cx=.5,cy=.5,zoom=1,rotation=0,flip=false,loadToken=0,raf=0,pointer=null,drawGeometry=null,closed=false;
    function close(result){
      if(closed)return;closed=true;
      loadToken++;if(raf)cancelAnimationFrame(raf);observer.disconnect();host.close();host.remove();
      if(current===session)current=null;if(previous&&previous.isConnected)previous.focus({preventScroll:true});
      source=oriented=output=null;resolve(result);
    }
    var session={cancel:function(){close(null);}};current=session;
    function feedback(message,error){$('importFeedback').hidden=!message;$('importFeedback').textContent=message||'';$('importFeedback').classList.toggle('error',!!error);}
    function region(){return target.animated&&$('importScope').value==='frame'?target.frame:{w:target.w,h:target.h};}
    function size(){var r=region(),value=$('importResolution').value;return value==='current'?{w:r.w,h:r.h}:value==='source'&&oriented?{w:oriented.width,h:oriented.height}:{w:Number(value),h:Math.max(1,Math.round(Number(value)*r.h/r.w))};}
    function resolutions(){
      var r=region(),locked=target.animated||target.skin;
      $('importResolution').innerHTML='<option value="current">'+r.w+' × '+r.h+' · Current</option>'+(locked?'':[16,32,64,128,256,512,1024].filter(function(w){return w!==r.w&&Math.round(w*r.h/r.w)>=1&&w*Math.round(w*r.h/r.w)<=MAX_PIXELS;}).map(function(w){return '<option value="'+w+'">'+w+' × '+Math.round(w*r.h/r.w)+'</option>';}).join('')+'<option value="source">Image size</option>');
      $('importResolution').disabled=locked;$('importResolutionHint').textContent=target.skin?'Minecraft skins keep their 64 × 64 layout.':target.animated?'Frame size stays fixed to preserve the animation.':'Keep the current size for a drop-in replacement.';
    }
    $('importDestination').textContent=target.name;$('importDestinationMeta').textContent=target.path;
    $('importTintRow').hidden=$('importTintHint').hidden=!target.tintColor;$('importTint').checked=!!target.viewTint;
    $('importScopeRow').hidden=!target.animated;
    if(target.animated)$('importScope').options[0].textContent='Frame '+(target.frameNumber+1);
    function scopeHint(){
      $('importScopeHint').textContent=$('importScope').value==='frame'?(target.shared>1?'This source frame appears '+target.shared+' times in the timeline. All its appearances update together.':'Only this frame changes. Timing and other frames stay intact.'):'Replaces every pixel in the sheet. Frame order and timing stay intact.';
      if(target.animated)$('importApplyHint').textContent=$('importScope').value==='frame'?'Apply to frame '+(target.frameNumber+1)+'. Undo restores its previous pixels.':'Apply to the entire sheet. Undo restores every frame.';
      else window.BenchI18n.text($('importApplyHint'),'Apply to {name}. You can undo this change.',{name:target.name});
    }
    resolutions();scopeHint();
    function orient(){
      if(!rotation&&!flip)oriented=source;
      else{oriented=document.createElement('canvas');oriented.width=rotation%2?source.height:source.width;oriented.height=rotation%2?source.width:source.height;
        var ctx=oriented.getContext('2d');ctx.translate(oriented.width/2,oriented.height/2);if(flip)ctx.scale(-1,1);ctx.rotate(rotation*Math.PI/2);ctx.drawImage(source,-source.width/2,-source.height/2);}
      cx=cy=.5;zoom=1;$('importZoom').value='100';queue();
    }
    function geometry(){
      var s=size(),sw=oriented.width,sh=oriented.height;
      if(fit==='cover'){
        var scale=Math.max(s.w/sw,s.h/sh)*zoom,cw=s.w/scale,ch=s.h/scale;
        var x=Math.max(0,Math.min(sw-cw,cx*sw-cw/2)),y=Math.max(0,Math.min(sh-ch,cy*sh-ch/2));
        cx=(x+cw/2)/sw;cy=(y+ch/2)/sh;return {sx:x,sy:y,sw:cw,sh:ch,dx:0,dy:0,dw:s.w,dh:s.h};
      }
      var scale=Math.min(s.w/sw,s.h/sh),dw=fit==='stretch'?s.w:sw*scale,dh=fit==='stretch'?s.h:sh*scale;
      return {sx:0,sy:0,sw:sw,sh:sh,dx:(s.w-dw)/2,dy:(s.h-dh)/2,dw:dw,dh:dh};
    }
    function render(){
      raf=0;if(!oriented)return;
      var s=size();if(!Number.isInteger(s.w)||!Number.isInteger(s.h)||s.w<1||s.h<1||s.w*s.h>MAX_PIXELS||Math.max(s.w,s.h)>32767){output=null;$('importApply').disabled=true;feedback('This output is too large. Choose a smaller size or import into one animation frame.',true);return;}
      var g=geometry(),cv=$('importOutput');if(cv.width!==s.w)cv.width=s.w;if(cv.height!==s.h)cv.height=s.h;
      var ctx=cv.getContext('2d');ctx.clearRect(0,0,s.w,s.h);ctx.imageSmoothingEnabled=$('importSampling').value==='smooth';ctx.imageSmoothingQuality='high';
      if($('importBackground').value==='solid'){ctx.fillStyle=$('importColor').value;ctx.fillRect(0,0,s.w,s.h);}
      ctx.drawImage(oriented,g.sx,g.sy,g.sw,g.sh,g.dx,g.dy,g.dw,g.dh);output=cv;
      $('importOutputSize').value=s.w+' × '+s.h;$('importPixelCount').textContent=(s.w*s.h).toLocaleString()+' pixels';
      cv.hidden=false;host.querySelector('.import-preview-empty').hidden=true;
      $('importTextureFrame').hidden=false;
      var preview=$('importPreview'),previewScale=Math.min(280/s.w,280/s.h,(preview.clientWidth-28)/s.w,(preview.clientHeight-28)/s.h);
      cv.style.width=s.w*previewScale+'px';cv.style.height=s.h*previewScale+'px';preview.style.setProperty('--preview-w',s.w*previewScale+'px');preview.style.setProperty('--preview-h',s.h*previewScale+'px');
      cv.style.imageRendering=$('importSampling').value==='pixel'?'pixelated':'auto';
      var tintCv=$('importTintOutput'),tinted=!!target.tintColor&&$('importTint').checked;cv.hidden=tinted;tintCv.hidden=!tinted;
      if(tinted){tintCv.width=s.w;tintCv.height=s.h;tintCv.style.width=cv.style.width;tintCv.style.height=cv.style.height;tintCv.style.imageRendering=cv.style.imageRendering;tintCv.getContext('2d').putImageData(MinecraftTextures.tintImage(ctx.getImageData(0,0,s.w,s.h),target.tintColor),0,0);}
      $('importPreview').classList.toggle('show-grid',$('importGrid').checked&&Math.max(s.w,s.h)<=64);
      $('importPreview').style.setProperty('--import-grid-w',s.w);$('importPreview').style.setProperty('--import-grid-h',s.h);
      $('importZoomRow').hidden=fit!=='cover';$('importZoomValue').value=Math.round(zoom*100)+'%';
      $('importCropHint').textContent=fit==='cover'?'Drag to move the crop. Arrow keys fine-tune it.':fit==='contain'?'Your whole image fits. Empty space keeps your chosen background.':'The image fills the texture by changing its proportions.';
      $('importFitHint').textContent={cover:'Fill the texture; crop the edges.',contain:'Show the whole image; keep its proportions.',stretch:'Use the full image; stretch it to the texture.'}[fit];
      var sourceCv=$('importSourceCanvas'),wrap=$('importSourceWrap'),width=wrap.clientWidth,height=wrap.clientHeight,ratio=Math.min(devicePixelRatio||1,2);
      sourceCv.width=Math.max(1,Math.round(width*ratio));sourceCv.height=Math.max(1,Math.round(height*ratio));
      var c=sourceCv.getContext('2d');c.scale(ratio,ratio);var scale=Math.min((width-32)/oriented.width,(height-32)/oriented.height),iw=oriented.width*scale,ih=oriented.height*scale,ix=(width-iw)/2,iy=(height-ih)/2;
      c.imageSmoothingEnabled=true;c.drawImage(oriented,ix,iy,iw,ih);
      var rect={x:ix+g.sx*scale,y:iy+g.sy*scale,w:g.sw*scale,h:g.sh*scale};drawGeometry={scale:scale,x:ix,y:iy,crop:rect};
      if(fit==='cover'){
        c.fillStyle='rgba(12,18,14,.6)';c.beginPath();c.rect(ix,iy,iw,ih);c.rect(rect.x,rect.y,rect.w,rect.h);c.fill('evenodd');
        c.strokeStyle='#e8f5de';c.lineWidth=1.5;c.strokeRect(rect.x,rect.y,rect.w,rect.h);
        c.strokeStyle='#e8f5de50';c.lineWidth=.5;for(var n=1;n<3;n++){c.beginPath();c.moveTo(rect.x+rect.w*n/3,rect.y);c.lineTo(rect.x+rect.w*n/3,rect.y+rect.h);c.moveTo(rect.x,rect.y+rect.h*n/3);c.lineTo(rect.x+rect.w,rect.y+rect.h*n/3);c.stroke();}
      }
      sourceCv.style.cursor=fit==='cover'?'move':'default';$('importApply').disabled=false;
    }
    function queue(){if(!raf)raf=requestAnimationFrame(render);}
    async function load(file){
      var token=++loadToken;if(!file)return;
      $('importApply').disabled=true;$('importOptions').disabled=true;$('importDrop').disabled=true;host.setAttribute('aria-busy','true');feedback('Preparing your image…');
      try{
        var result=await read(file);if(token!==loadToken)return;
        if(target.skin&&(result.canvas.width!==64||result.canvas.height!==64))throw new Error('Skins need a prepared 64 × 64 Minecraft layout. Open a texture pack to turn a photo into a block texture.');
        source=result.canvas;rotation=0;flip=false;$('importFlip').setAttribute('aria-pressed','false');
        $('importSampling').value=sampling(source,result.kind);
        $('importDrop').hidden=true;$('importSourceWrap').hidden=false;$('importFileInfo').hidden=false;$('importCropHint').hidden=false;$('importChange').hidden=false;
        $('importFileName').textContent=file.name;$('importFileMeta').textContent=source.width+' × '+source.height+' · '+(file.size<1048576?Math.max(1,Math.round(file.size/1024))+' KB':(file.size/1048576).toFixed(1)+' MB');
        $('importOptions').disabled=false;feedback('');orient();
      }catch(error){if(token!==loadToken)return;feedback(error.message+(source?' Your previous image is still selected.':''),true);$('importOptions').disabled=!source;if(source)queue();}
      finally{if(token===loadToken){$('importDrop').disabled=false;host.removeAttribute('aria-busy');$('importFile').value='';}}
    }
    $('importDrop').onclick=$('importChange').onclick=function(){$('importFile').click();};$('importFile').onchange=function(){if(this.files[0])load(this.files[0]);};
    host.addEventListener('dragover',function(e){if(e.dataTransfer&&Array.from(e.dataTransfer.types).includes('Files')){e.preventDefault();e.stopPropagation();host.classList.add('file-over');}});
    host.addEventListener('dragleave',function(e){if(!host.contains(e.relatedTarget))host.classList.remove('file-over');});
    host.addEventListener('drop',function(e){e.preventDefault();e.stopPropagation();host.classList.remove('file-over');if(e.dataTransfer.files.length!==1){feedback('Choose one image at a time so you can preview each texture.',true);return;}load(e.dataTransfer.files[0]);});
    host.addEventListener('dragenter',function(e){e.stopPropagation();});
    host.addEventListener('paste',function(e){if(e.target.closest('input:not([type=range]),textarea'))return;var files=e.clipboardData&&Array.from(e.clipboardData.files);if(files&&files.length){e.preventDefault();e.stopPropagation();if(files.length===1)load(files[0]);else feedback('Paste one image at a time.',true);}});
    host.querySelectorAll('[data-fit]').forEach(function(b){b.onclick=function(){fit=b.dataset.fit;host.querySelectorAll('[data-fit]').forEach(function(other){other.setAttribute('aria-pressed',String(other===b));});queue();};});
    $('importScope').onchange=function(){resolutions();scopeHint();cx=cy=.5;zoom=1;$('importZoom').value='100';feedback('');queue();};
    $('importResolution').onchange=function(){cx=cy=.5;queue();};
    $('importZoom').oninput=function(){zoom=Number(this.value)/100;queue();};
    $('importReset').onclick=function(){cx=cy=.5;zoom=1;$('importZoom').value='100';queue();};
    $('importRotate').onclick=function(){rotation=(rotation+1)%4;orient();};
    $('importFlip').onclick=function(){flip=!flip;this.setAttribute('aria-pressed',String(flip));orient();};
    ['importSampling','importGrid','importColor','importTint'].forEach(function(id){$(id).addEventListener('input',queue);});
    $('importBackdrop').onchange=function(){$('importPreview').dataset.backdrop=this.value;};
    $('importBackground').onchange=function(){$('importColorRow').hidden=this.value!=='solid';queue();};
    var sourceCv=$('importSourceCanvas');
    sourceCv.addEventListener('pointerdown',function(e){if(e.button!==0||!oriented||fit!=='cover'||!drawGeometry)return;e.preventDefault();pointer={id:e.pointerId,x:e.clientX,y:e.clientY};sourceCv.setPointerCapture(e.pointerId);sourceCv.focus({preventScroll:true});});
    sourceCv.addEventListener('pointermove',function(e){if(!pointer||pointer.id!==e.pointerId||!drawGeometry)return;cx+=(e.clientX-pointer.x)/drawGeometry.scale/oriented.width;cy+=(e.clientY-pointer.y)/drawGeometry.scale/oriented.height;pointer.x=e.clientX;pointer.y=e.clientY;queue();});
    ['pointerup','pointercancel','lostpointercapture'].forEach(function(name){sourceCv.addEventListener(name,function(){pointer=null;});});
    sourceCv.addEventListener('keydown',function(e){if(!oriented||fit!=='cover')return;var step=e.shiftKey?10:1;if(e.key==='ArrowLeft')cx-=step/oriented.width;else if(e.key==='ArrowRight')cx+=step/oriented.width;else if(e.key==='ArrowUp')cy-=step/oriented.height;else if(e.key==='ArrowDown')cy+=step/oriented.height;else return;e.preventDefault();queue();});
    $('importApply').onclick=function(){if(!source||host.hasAttribute('aria-busy'))return;if(raf){cancelAnimationFrame(raf);raf=0;}render();if(!output||this.disabled)return;close({data:output.getContext('2d').getImageData(0,0,output.width,output.height),scope:target.animated?$('importScope').value:'texture'});};
    $('importCancel').onclick=$('importClose').onclick=function(){close(null);};host.addEventListener('cancel',function(e){e.preventDefault();close(null);});
    var observer=new ResizeObserver(queue);observer.observe($('importSourceWrap'));observer.observe($('importPreview'));
    var promise=new Promise(function(done){resolve=done;});host.showModal();if(window.Motion)window.Motion.surface(host);$('importDrop').focus();if(file)load(file);return promise;
  }
  window.ImageImporter={open:open,read:read,close:function(){if(current)current.cancel();}};
})();
