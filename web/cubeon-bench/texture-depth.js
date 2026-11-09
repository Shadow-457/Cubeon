(function () {
  'use strict';
  function contains(selection,x,y){
    if(!selection)return true;
    return x>=selection.x&&y>=selection.y&&x<selection.x+selection.w&&y<selection.y+selection.h&&
      (!selection.mask||!!selection.mask[(y-selection.y)*selection.w+x-selection.x]);
  }
  function lasso(points,bounds){
    if(!points.length)return null;
    if(points.length<3)return points[0][0]>=bounds.x&&points[0][1]>=bounds.y&&points[0][0]<bounds.x+bounds.w&&points[0][1]<bounds.y+bounds.h?{x:points[0][0],y:points[0][1],w:1,h:1}:null;
    var x=Math.max(bounds.x,Math.floor(Math.min.apply(null,points.map(function(p){return p[0]})))),
      y=Math.max(bounds.y,Math.floor(Math.min.apply(null,points.map(function(p){return p[1]}))));
    var w=Math.min(bounds.x+bounds.w,Math.ceil(Math.max.apply(null,points.map(function(p){return p[0]})))+1)-x,
      h=Math.min(bounds.y+bounds.h,Math.ceil(Math.max.apply(null,points.map(function(p){return p[1]})))+1)-y;
    if(w<=0||h<=0)return null;
    var selection={x:x,y:y,w:w,h:h,mask:new Uint8Array(w*h)},count=0;
    // Scan each row once; checking every pixel against every segment stalls large textures.
    for(var py=y;py<y+h;py++){
      var cy=py+.5,crossings=[];
      for(var i=0,j=points.length-1;i<points.length;j=i++){
        var a=points[i],b=points[j];
        if((a[1]>cy)!==(b[1]>cy))crossings.push((b[0]-a[0])*(cy-a[1])/(b[1]-a[1])+a[0]);
      }
      crossings.sort(function(a,b){return a-b;});
      for(var i=0;i+1<crossings.length;i+=2){
        var start=Math.max(x,Math.ceil(crossings[i]-.5)),end=Math.min(x+w,Math.ceil(crossings[i+1]-.5));
        if(end>start){selection.mask.fill(1,(py-y)*w+start-x,(py-y)*w+end-x);count+=end-start;}
      }
    }
    selection.count=count;return count?selection:null;
  }
  function outline(selection){
    if(selection.edges)return selection.edges;
    var edges=[];
    for(var y=selection.y;y<selection.y+selection.h;y++)for(var x=selection.x;x<selection.x+selection.w;x++)if(contains(selection,x,y)){
      if(!contains(selection,x,y-1))edges.push([x,y,x+1,y]);
      if(!contains(selection,x+1,y))edges.push([x+1,y,x+1,y+1]);
      if(!contains(selection,x,y+1))edges.push([x,y+1,x+1,y+1]);
      if(!contains(selection,x-1,y))edges.push([x,y,x,y+1]);
    }
    selection.edges=edges;return edges;
  }
  function layer(doc){
    if(doc.depthLayer&&doc.depthLayer.width===doc.w&&doc.depthLayer.height===doc.h)return doc.depthLayer;
    if(doc.surface)doc.depthLayer=window.TextureSurface.generate(doc.composite||doc.data,doc.surface,doc.e).base;
    else{
      doc.depthLayer=new ImageData(doc.w,doc.h);
      for(var i=0;i<doc.depthLayer.data.length;i+=4)doc.depthLayer.data.set([128,128,128,255],i);
    }
    return doc.depthLayer;
  }
  function save(doc){
    doc.surface=Object.assign({version:1,depth:100,shine:15,metal:false},doc.surface||{},
      {invert:false,smooth:0,height:window.TextureCodec.encode(layer(doc))});
  }
  function stroke(image){return {before:new Uint8ClampedArray(image.data),weights:new Float32Array(image.width*image.height)};}
  function pixel(image,state,x,y,operation,amount,value,weight){
    if(x<0||y<0||x>=image.width||y>=image.height)return;
    weight=Math.max(0,Math.min(1,weight));
    var index=y*image.width+x;if(weight<=state.weights[index])return;
    state.weights[index]=weight;var i=index*4,base=state.before[i],target=operation==='set'?value/100*255:operation==='reset'?128:base+(operation==='lower'?-1:1)*amount/100*255;
    var level=Math.round(Math.max(0,Math.min(255,base+(target-base)*weight)));
    image.data.set([level,level,level,255],i);
  }
  function adjust(image,selection,bounds,operation,amount,value){
    var state=stroke(image),x0=Math.max(0,bounds.x,selection?selection.x:0),y0=Math.max(0,bounds.y,selection?selection.y:0),
      x1=Math.min(image.width,bounds.x+bounds.w,selection?selection.x+selection.w:image.width),y1=Math.min(image.height,bounds.y+bounds.h,selection?selection.y+selection.h:image.height);
    for(var y=y0;y<y1;y++)for(var x=x0;x<x1;x++)if(contains(selection,x,y))pixel(image,state,x,y,operation,amount,value,1);
  }
  function brush(image,state,x,y,size,softness,selection,bounds,operation,amount,value,pressure){
    var radius=size/2,startX=x-((size-1)>>1),startY=y-((size-1)>>1);
    for(var dy=0;dy<size;dy++)for(var dx=0;dx<size;dx++){
      var px=startX+dx,py=startY+dy;
      if(px<bounds.x||py<bounds.y||px>=bounds.x+bounds.w||py>=bounds.y+bounds.h||!contains(selection,px,py))continue;
      var weight=1;
      if(softness&&size>1){
        var distance=Math.hypot(dx-(size-1)/2,dy-(size-1)/2)/radius,inner=1-softness/100;
        weight=distance<=inner?1:Math.max(0,(1-distance)/(1-inner));
      }
      pixel(image,state,px,py,operation,amount,value,weight*(pressure===undefined?1:pressure));
    }
  }
  function overlay(image){
    var result=new ImageData(image.width,image.height);
    for(var i=0;i<image.data.length;i+=4){var level=image.data[i],up=level>=128;result.data.set(up?[44,173,105,Math.round((level-128)/127*160)]:[110,93,222,Math.round((128-level)/128*160)],i);}
    return result;
  }
  window.TextureDepth={contains:contains,lasso:lasso,outline:outline,layer:layer,save:save,stroke:stroke,pixel:pixel,adjust:adjust,brush:brush,overlay:overlay};
})();
