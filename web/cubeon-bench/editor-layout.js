(function () {
  'use strict';
  var CB=window.CB,ed=document.getElementById('ed'),body=ed.querySelector('.edmn');
  var widths={left:Number(CB.D.set.editorLeft)||248,right:Number(CB.D.set.editorRight)||288};
  var min={left:180,right:248},frame=0;
  function refresh(){if(frame)return;frame=requestAnimationFrame(function(){frame=0;if(window.Ed.refreshLayout)window.Ed.refreshLayout(true);});}
  function apply(side,value){
    var other=widths[side==='left'?'right':'left'],rail=ed.classList.contains('frames-visible')&&innerWidth>1100?224:0,available=body.clientWidth?body.clientWidth-other-rail-320:460;
    var maximum=Math.max(min[side],Math.min(460,available));
    widths[side]=Math.round(Math.max(min[side],Math.min(maximum,value)));
    ed.style.setProperty('--editor-'+side,widths[side]+'px');
    var handle=document.getElementById('resize-'+side);if(handle){handle.setAttribute('aria-valuenow',widths[side]);handle.setAttribute('aria-valuemax',maximum);}
    refresh();
  }
  ['left','right'].forEach(function(side){
    var handle=document.createElement('div');handle.id='resize-'+side;handle.className='sidebar-resizer side-'+side;
    handle.tabIndex=0;handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');
    handle.setAttribute('aria-label','Resize '+side+' editor sidebar');handle.setAttribute('aria-valuemin',min[side]);handle.setAttribute('aria-valuemax','460');
    handle.title='Drag to resize · arrow keys adjust width';body.appendChild(handle);var drag=null;
    handle.addEventListener('pointerdown',function(event){if(event.button!==0)return;event.preventDefault();var panel=document.getElementById(side==='left'?'edLeft':'edRight');widths[side]=Math.round(panel.getBoundingClientRect().width);drag={x:event.clientX,width:widths[side]};handle.setPointerCapture(event.pointerId);ed.classList.add('resizing');});
    handle.addEventListener('pointermove',function(event){if(drag){if(event.buttons!==1){end();return}apply(side,drag.width+(event.clientX-drag.x)*(side==='left'?1:-1)*(document.documentElement.dir==='rtl'?-1:1));}});
    function end(){if(!drag)return;drag=null;ed.classList.remove('resizing');CB.D.set.editorLeft=widths.left;CB.D.set.editorRight=widths.right;CB.save();window.Ed.refreshLayout();}
    handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);handle.addEventListener('lostpointercapture',end);window.addEventListener('pointerup',end);window.addEventListener('blur',end);
    handle.addEventListener('keydown',function(event){if(event.key==='ArrowLeft'||event.key==='ArrowRight'){event.preventDefault();apply(side,widths[side]+(event.key==='ArrowRight'?1:-1)*(side==='left'?1:-1)*(document.documentElement.dir==='rtl'?-1:1)*16);CB.D.set.editorLeft=widths.left;CB.D.set.editorRight=widths.right;CB.save();}});
    handle.addEventListener('dblclick',function(){apply(side,side==='left'?248:288);CB.D.set.editorLeft=widths.left;CB.D.set.editorRight=widths.right;CB.save();});
    apply(side,widths[side]);
  });
  CB.ready.then(function(){apply('left',Number(CB.D.set.editorLeft)||248);apply('right',Number(CB.D.set.editorRight)||288);},function(){});
  var trigger=document.getElementById('edContext'),menu=document.getElementById('textureMenu');
  function close(){menu.hidden=true;trigger.setAttribute('aria-expanded','false');}
  function open(){var r=trigger.getBoundingClientRect();menu.hidden=false;menu.style.top=(r.bottom+8)+'px';menu.style.right='16px';trigger.setAttribute('aria-expanded','true');Motion.surface(menu);}
  trigger.addEventListener('click',function(){if(menu.hidden)open();else close();});
  trigger.addEventListener('keydown',function(event){if(event.key==='ArrowDown'){event.preventDefault();open();menu.querySelector('button').focus();}});
  menu.addEventListener('click',function(event){if(event.target.closest('button'))close();});
  document.addEventListener('pointerdown',function(event){if(!menu.hidden&&!menu.contains(event.target)&&!trigger.contains(event.target))close();});
  document.addEventListener('keydown',function(event){if(!menu.hidden&&event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close();trigger.focus();}},true);
  menu.addEventListener('keydown',function(event){if(event.key==='ArrowDown'||event.key==='ArrowUp'){event.preventDefault();var buttons=Array.from(menu.querySelectorAll('button'));var i=buttons.indexOf(document.activeElement);buttons[(i+(event.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length].focus();}});
  function fit(){if(ed.classList.contains('show')&&innerWidth>900){apply('left',widths.left);apply('right',widths.right);window.Ed.refreshLayout();}}
  window.addEventListener('resize',fit);window.EditorLayout={fit:fit};
})();
