(function () {
  'use strict';
  var LIMIT = 1048576, codec = window.TextureCodec;
  function number(value, fallback, min, max) {
    return typeof value === 'number' && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;
  }
  function settings(value) {
    if (!value) return null;
    if (typeof value !== 'object' || Array.isArray(value) || value.version !== 1) throw new Error('This depth-map format is not supported.');
    var result = {version:1, depth:number(value.depth,40,0,100), shine:number(value.shine,15,0,100),
      smooth:Math.round(number(value.smooth,0,0,2)), invert:value.invert === true, metal:value.metal === true};
    if (value.height) {
      if (!Number.isInteger(value.height.w) || !Number.isInteger(value.height.h) || value.height.w * value.height.h > LIMIT) throw new Error('Height maps support up to one million pixels.');
      codec.decode(value.height);
      result.height = {w:value.height.w, h:value.height.h, pixels:value.height.pixels};
    }
    return result;
  }
  function validId(id) { return typeof id==='string' && /^[a-z0-9_./:-]+$/.test(id) && !id.split('/').includes('..') && !['__proto__','constructor','prototype'].includes(id); }
  function dictionary(value) {
    if (!value) return {};
    if (typeof value !== 'object' || Array.isArray(value)) throw new Error('The project contains invalid depth maps.');
    var result = Object.create(null), ids = Object.keys(value);
    if (ids.length > 4096) throw new Error('The project contains too many depth maps.');
    ids.forEach(function (id) { if (!validId(id)) throw new Error('The project contains an invalid depth-map path.'); if (value[id]) result[id] = settings(value[id]); });
    return result;
  }
  function supported(image) { return !!image && image.width > 0 && image.height > 0 && image.width * image.height <= LIMIT; }
  function fit(image,w,h){
    if(w*h>LIMIT)throw new Error('Height maps support up to one million pixels.');
    var result=new ImageData(w,h);
    for(var y=0;y<h;y++)for(var x=0;x<w;x++){
      var sx=Math.min(image.width-1,Math.floor(x*image.width/w)),sy=Math.min(image.height-1,Math.floor(y*image.height/h));
      result.data.set(image.data.subarray((sy*image.width+sx)*4,(sy*image.width+sx)*4+4),(y*w+x)*4);
    }
    return result;
  }
  function tileSize(image, entry) {
    var result = {w:image.width,h:image.height};
    try {
      if (entry && entry.animation) {
        var effective = window.TextureAnimation.effectiveEntry(entry, undefined, image.width, image.height);
        var frame = window.TextureAnimation.frameRect(window.TextureAnimation.layout(effective), 0);
        result = {w:frame.w,h:frame.h};
      }
    } catch (_) {}
    return result;
  }
  function base(image, options, entry, custom) {
    if (!supported(image)) throw new Error('Add depth to textures with up to one million pixels.');
    options = settings(options);
    var w = image.width, h = image.height, a = image.data, count = w * h, values = new Float32Array(count);
    var imported = custom || (options.height && codec.decode(options.height)), min = 1, max = 0;
    for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
      var i = y * w + x, value;
      if (imported) {
        var sx = Math.min(imported.width - 1, Math.floor(x * imported.width / w)), sy = Math.min(imported.height - 1, Math.floor(y * imported.height / h)), p = (sy * imported.width + sx) * 4;
        value = (imported.data[p] * .2126 + imported.data[p+1] * .7152 + imported.data[p+2] * .0722) / 255;
      } else value = (a[i*4] * .2126 + a[i*4+1] * .7152 + a[i*4+2] * .0722) / 255;
      values[i] = value;
      if (a[i*4+3]) { min = Math.min(min,value); max = Math.max(max,value); }
    }
    for (var i = 0; i < count; i++) {
      var value = imported ? values[i] : max > min ? (values[i] - min) / (max - min) : .5;
      values[i] = a[i*4+3] ? options.invert ? 1-value : value : 0;
    }
    var tile = tileSize(image,entry);
    function sample(array,x,y,originX,originY) {
      var tw = Math.min(tile.w,w-originX), th = Math.min(tile.h,h-originY);
      return array[(originY+(y-originY+th)%th)*w+originX+(x-originX+tw)%tw];
    }
    for (var pass = 0; pass < options.smooth; pass++) {
      var next = new Float32Array(count);
      for (var y = 0; y < h; y++) for (var x = 0; x < w; x++) {
        var ox = Math.floor(x/tile.w)*tile.w, oy = Math.floor(y/tile.h)*tile.h, sum = 0;
        for (var dy=-1;dy<=1;dy++) for (var dx=-1;dx<=1;dx++) sum += sample(values,x+dx,y+dy,ox,oy)*(dx===0?2:1)*(dy===0?2:1);
        next[y*w+x] = a[(y*w+x)*4+3] ? sum/16 : 0;
      }
      values = next;
    }
    return {values:values,tile:tile};
  }
  function generate(image, options, entry, custom) {
    options = settings(options);
    var raw = base(image,options,entry,custom), w=image.width,h=image.height, tile=raw.tile;
    var height = new ImageData(w,h), original = new ImageData(w,h), normal = new ImageData(w,h), rgb = new ImageData(w,h), material = new ImageData(w,h);
    var values = new Float32Array(w*h), strength=options.depth/100;
    for (var i=0;i<w*h;i++) {
      values[i] = 1-(1-raw.values[i])*strength;
      var level=Math.round(values[i]*255), source=Math.round(raw.values[i]*255);
      height.data.set([level,level,level,255],i*4); original.data.set([source,source,source,255],i*4);
    }
    function at(x,y,ox,oy) {
      var tw=Math.min(tile.w,w-ox),th=Math.min(tile.h,h-oy);
      return values[(oy+(y-oy+th)%th)*w+ox+(x-ox+tw)%tw];
    }
    for (var y=0;y<h;y++) for (var x=0;x<w;x++) {
      var i=(y*w+x)*4, ox=Math.floor(x/tile.w)*tile.w,oy=Math.floor(y/tile.h)*tile.h;
      var nx=-(at(x+1,y,ox,oy)-at(x-1,y,ox,oy))*tile.w*.35/4;
      var ny=(at(x,y+1,ox,oy)-at(x,y-1,ox,oy))*tile.h*.35/4;
      var length=Math.hypot(nx,ny,1),r=Math.round((nx/length*.5+.5)*255),g=Math.round((ny/length*.5+.5)*255);
      if (!image.data[i+3]) {r=128;g=128;}
      // LabPBR: normal X/Y, ambient occlusion, height. Blue is not normal Z.
      normal.data.set([r,g,255,height.data[i]],i);
      rgb.data.set([r,g,Math.round((1/length*.5+.5)*255),255],i);
      // LabPBR: perceptual smoothness, dielectric F0 / iron ID, porosity, emission.
      // 255 in alpha disables emission; it does not mean maximum emission.
      material.data.set([Math.round(options.shine/100*255),options.metal?230:10,0,255],i);
    }
    return {height:height,base:original,normal:normal,normalRGB:rgb,material:material,settings:options};
  }
  var crcTable=new Uint32Array(256);
  for(var c=0;c<256;c++){
    var checksum=c;for(var bit=0;bit<8;bit++)checksum=checksum&1?0xedb88320^(checksum>>>1):checksum>>>1;
    crcTable[c]=checksum>>>0;
  }
  function pngChunk(type,data){
    var bytes=new Uint8Array(data.length+12),view=new DataView(bytes.buffer);
    view.setUint32(0,data.length);bytes.set(new TextEncoder().encode(type),4);bytes.set(data,8);
    var crc=0xffffffff;for(var i=4;i<bytes.length-4;i++)crc=crcTable[(crc^bytes[i])&255]^(crc>>>8);
    view.setUint32(bytes.length-4,(crc^0xffffffff)>>>0);return bytes;
  }
  function png(image){
    if(!supported(image))throw new Error('Depth maps support up to one million pixels.');
    // LabPBR uses alpha for height. Canvas PNG encoding premultiplies RGB and
    // destroys normal/AO values at low or zero height, so write the channels raw.
    var stride=image.width*4,rows=new Uint8Array((stride+1)*image.height);
    for(var y=0;y<image.height;y++)rows.set(image.data.subarray(y*stride,(y+1)*stride),y*(stride+1)+1);
    var header=new Uint8Array(13),view=new DataView(header.buffer);view.setUint32(0,image.width);view.setUint32(4,image.height);
    header[8]=8;header[9]=6;
    return new Blob([new Uint8Array([137,80,78,71,13,10,26,10]),pngChunk('IHDR',header),
      pngChunk('IDAT',window.fflate.zlibSync(rows,{level:6})),pngChunk('IEND',new Uint8Array())],{type:'image/png'});
  }
  async function readPNG(input) {
    var blob=input instanceof Blob?input:new Blob([input],{type:'image/png'});
    if (blob.size>16777216) throw new Error('Choose a height map smaller than 16 MB.');
    var url=URL.createObjectURL(blob),image=new Image();
    try {
      await new Promise(function (resolve,reject) {image.onload=resolve;image.onerror=function(){reject(new Error('This height map could not be opened.'));};image.src=url;});
      if (image.naturalWidth*image.naturalHeight>LIMIT) throw new Error('Height maps support up to one million pixels.');
      var cv=document.createElement('canvas');cv.width=image.naturalWidth;cv.height=image.naturalHeight;
      var ctx=cv.getContext('2d');ctx.drawImage(image,0,0);return ctx.getImageData(0,0,cv.width,cv.height);
    } finally {URL.revokeObjectURL(url);}
  }
  function heightPath(entry) {
    var path=entry.path||'assets/minecraft/'+entry.src;
    return '.cubeon/heightmaps/'+path.replace(/^assets\//,'').replace('/textures/','/');
  }
  async function exportMaps(image,options,entry,path) {
    var maps=generate(image,options,entry),files=Object.create(null),meta=settings(options);
    files[path.replace(/\.png$/,'_n.png')]=new Uint8Array(await png(maps.normal).arrayBuffer());
    files[path.replace(/\.png$/,'_s.png')]=new Uint8Array(await png(maps.material).arrayBuffer());
    files[heightPath(entry)]=new Uint8Array(await png(meta.height?codec.decode(meta.height):maps.base).arrayBuffer());
    if (meta.height) {delete meta.height;meta.heightFile=heightPath(entry);}
    return {files:files,settings:meta};
  }
  async function importMaps(value,files) {
    if (!value) return {};
    var result=Object.create(null);
    if (typeof value!=='object'||Array.isArray(value)||Object.keys(value).length>4096) throw new Error('The pack contains invalid depth maps.');
    for (var id of Object.keys(value)) {
      if (!validId(id)) throw new Error('The pack contains an invalid depth-map path.');
      var raw=value[id];if(!raw)continue;
      var row=settings(raw);
      if (raw.heightFile) {
        if (typeof raw.heightFile!=='string'||!raw.heightFile.startsWith('.cubeon/heightmaps/')||raw.heightFile.split('/').includes('..')||!files[raw.heightFile]) throw new Error('The pack is missing its editable height map.');
        row.height=codec.encode(await readPNG(files[raw.heightFile]));
      }
      result[id]=row;
    }
    return result;
  }
  window.TextureSurface={settings:settings,dictionary:dictionary,supported:supported,fit:fit,generate:generate,png:png,readPNG:readPNG,
    exportMaps:exportMaps,importMaps:importMaps,heightPath:heightPath,validId:validId};
})();
