(function () {
  'use strict';
  var data=window.BenchLanguageData,root=document.documentElement,records=new WeakMap(),bindings=new WeakMap(),preferred='auto',language='en',started=false,observer;
  var attributes=['title','placeholder','aria-label','alt'];
  var protectedText='script,style,svg,code,pre,kbd,[translate="no"],[data-no-i18n],.brand,.sbb,.wordmark,.pn,.av,.tx>span,.rs>span,.bt>span,.bt>small,.tab[data-id]:not([data-id="preview"])>span,.folder-button:not([data-folder=""]),#edName,#edPath,#canvasTextureName,#surfaceTextureLabel,#pvT,#importDestination,#importDestinationMeta,#importFileName,#importFileMeta,#s2,#usr b,.phd b';
  function normalize(code){
    if(typeof code!=='string')return null;code=code.toLowerCase().replace(/_/g,'-');
    if(code==='auto')return 'auto';if(code.startsWith('zh'))return 'zh-CN';if(code.startsWith('pt'))return 'pt-BR';
    var base=code.split('-')[0],found=data.languages.find(function(row){return row.code.toLowerCase()===code||row.code===base;});return found?found.code:null;
  }
  function resolve(code,languages){
    var selected=normalize(code);if(selected&&selected!=='auto')return selected;
    for(var candidate of languages||navigator.languages||[navigator.language]){var match=normalize(candidate);if(match&&match!=='auto')return match;}
    return 'en';
  }
  function compact(value){return value.replace(/\s+/g,' ').trim();}
  function replace(template,values){return template.replace(/\{(\w+)\}/g,function(all,key){return values&&values[key]!==undefined?String(values[key]):all;});}
  var patterns=[];
  Object.keys(data.messages).concat(Object.keys(data.aliases)).forEach(function(source){
    if(!/\{\w+\}/.test(source)||/\{(?:name|greeting|query|error|text)\}/.test(source))return;
    var names=[],expression='',last=0,matcher=/\{(\w+)\}/g,match;
    while(match=matcher.exec(source)){expression+=source.slice(last,match.index).replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'([\\p{N}.,٬٫\\u00a0\\u202f]+)';names.push(match[1]);last=matcher.lastIndex;}
    expression+=source.slice(last).replace(/[.*+?^${}()|[\]\\]/g,'\\$&');patterns.push({source:source,names:names,regex:new RegExp('^'+expression+'$','u')});
  });
  function t(source,values){
    if(typeof source!=='string')return source;
    var key=compact(source),parameters=values;
    if(!parameters&&!data.messages[key]&&!data.aliases[key])for(var pattern of patterns){var match=pattern.regex.exec(key);if(match){key=pattern.source;parameters={};pattern.names.forEach(function(name,index){parameters[name]=match[index+1];});break;}}
    var canonical=data.aliases[key]||key,index=data.languages.findIndex(function(row){return row.code===language;})-1;
    var translated=index>=0&&data.messages[canonical]&&data.messages[canonical][index];
    var result=replace(translated||source,parameters);
    if(language==='en'&&parameters&&Number(parameters.count)===1)result=result.replace(/\b(pixels|textures|frames|projects)\b/g,function(word){return word.slice(0,-1);});
    if(!translated){
      if(language!=='en'&&source.includes(' · '))return source.split(' · ').map(function(part){return t(part);}).join(' · ');
      return result;
    }
    return source.match(/^\s*/)[0]+result+source.match(/\s*$/)[0];
  }
  function track(node,attribute,value){
    var items=records.get(node)||{};records.set(node,items);var slot=attribute||'text',row=items[slot];
    if(!row||value!==row.last)row=items[slot]={source:value,last:value};
    var result=t(row.source);row.last=result;
    if(result!==value){if(attribute)node.setAttribute(attribute,result);else node.nodeValue=result;}
  }
  function apply(node){
    if(node.nodeType===3){if(node.parentElement&&!node.parentElement.closest(protectedText)&&compact(node.nodeValue))track(node,null,node.nodeValue);return;}
    if(node.nodeType!==1)return;
    var binding=bindings.get(node);
    if(binding){var result=t(binding.source,binding.values);if(node.textContent!==result)node.textContent=result;}
    if(node.closest('script,style,svg,[translate="no"],[data-no-i18n]'))return;
    // A static paragraph may split one sentence with bold/emphasis tags.
    // Translate it together, retaining its English markup for switching back.
    if(!binding&&node.tagName==='P'&&!node.closest(protectedText)){
      var items=records.get(node)||{},rich=items.rich,value=node.textContent;
      if(rich&&value!==rich.last)rich=null;
      if(!rich&&node.children.length&&Array.from(node.children).every(function(child){return /^(B|STRONG|EM)$/.test(child.tagName)&&!child.children.length;})){
        var key=compact(value);if(data.messages[key]||data.aliases[key])rich={source:value,html:node.innerHTML,last:value};
      }
      if(rich){
        items.rich=rich;records.set(node,items);var translated=t(rich.source);rich.last=translated;
        if(translated!==value){if(language==='en')node.innerHTML=rich.html;else node.textContent=translated;}
      }else if(items.rich)delete items.rich;
    }
    if(node.tagName==='OPTION'&&!node.hasAttribute('value'))node.setAttribute('value',node.value);
    attributes.forEach(function(attribute){var value=node.getAttribute(attribute);if(value)track(node,attribute,value);});
  }
  function translate(target){
    if(!target)return;apply(target);
    if(target.nodeType===3)return;
    var walker=document.createTreeWalker(target,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT),node;
    while(node=walker.nextNode())apply(node);
  }
  function text(element,source,values){bindings.set(element,{source:source,values:values});element.textContent=t(source,values);}
  function fillPicker(select){
    select.replaceChildren();
    var auto=document.createElement('option');auto.value='auto';auto.textContent='Use browser language';select.appendChild(auto);
    data.languages.forEach(function(row){var option=document.createElement('option');option.value=row.code;option.lang=row.code;option.dir=row.dir||'ltr';option.setAttribute('translate','no');option.textContent=row.name;select.appendChild(option);});
    select.value=preferred;select.dir='auto';
  }
  function applyLanguage(code){
    preferred=normalize(code)||'auto';language=resolve(preferred);var row=data.languages.find(function(row){return row.code===language;});
    root.lang=language;root.dir=row.dir||'ltr';
    if(started){
      translate(document.body);document.querySelectorAll('[data-bench-language]').forEach(function(select){select.value=preferred;});
      document.dispatchEvent(new CustomEvent('bench-language-change',{detail:{language:language,preferred:preferred}}));
    }
  }
  function set(code,persist){
    if(!normalize(code))return false;
    applyLanguage(code);try{localStorage.setItem('cb-language',preferred);}catch(_){}
    if(persist!==false&&window.CB){window.CB.D.set.language=preferred;window.CB.save();}
    return true;
  }
  function showPicker(){
    if(!window.AppDialog)return;
    var html='<input class="command-search" id="benchLanguageSearch" type="search" placeholder="Search languages" aria-label="Search languages" autocomplete="off"><div class="bench-language-list">';
    html+=[{code:'auto',name:'Use browser language',english:'Automatic'}].concat(data.languages).map(function(row){return '<button class="bench-language-option" type="button" data-language="'+row.code+'" aria-pressed="'+(preferred===row.code)+'"><span'+(row.code!=='auto'?' translate="no" lang="'+row.code+'" dir="auto"':'')+'>'+row.name+'</span><small translate="no">'+(row.english||row.name)+'</small></button>';}).join('')+'</div><p id="benchLanguageEmpty" hidden>No matching languages.</p>';
    window.AppDialog.open({title:'Language',accept:'Close',noCancel:true,html:html});var host=document.getElementById('appDialog');translate(host);
    host.querySelectorAll('[data-language]').forEach(function(button){button.onclick=function(){set(button.dataset.language);window.AppDialog.close(true);};});
    var search=host.querySelector('#benchLanguageSearch');search.oninput=function(){var query=this.value.toLocaleLowerCase(),count=0;host.querySelectorAll('[data-language]').forEach(function(button){button.hidden=!(button.textContent+' '+button.dataset.language).toLocaleLowerCase().includes(query);if(!button.hidden)count++;});host.querySelector('#benchLanguageEmpty').hidden=!!count;};search.focus();
  }
  try{preferred=normalize(localStorage.getItem('cb-language'))||'auto';}catch(_){}
  applyLanguage(preferred);
  function start(){
    if(started)return;started=true;
    document.querySelectorAll('[data-bench-language]').forEach(function(select){fillPicker(select);select.addEventListener('change',function(){set(this.value);});});
    document.querySelectorAll('[data-bench-language-open]').forEach(function(button){button.addEventListener('click',showPicker);});
    translate(document.body);
    observer=new MutationObserver(function(changes){var roots=new Set();changes.forEach(function(change){if(change.type==='childList')change.addedNodes.forEach(function(node){roots.add(node);});else roots.add(change.target);});roots.forEach(translate);});
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:attributes});
    if(window.CB)window.CB.ready.then(function(){
      var saved;try{saved=normalize(localStorage.getItem('cb-language'));}catch(_){}
      if(!saved&&normalize(window.CB.D.set.language))applyLanguage(window.CB.D.set.language);
      window.CB.D.set.language=preferred;document.querySelectorAll('[data-bench-language]').forEach(function(select){select.value=preferred;});
    },function(){});
    document.addEventListener('bench-language-change',function(){if(window.CB)window.CB.renderAll();if(window.EditorLayout)window.EditorLayout.fit();});
    window.addEventListener('storage',function(event){if(event.key==='cb-language'){applyLanguage(normalize(event.newValue)||'auto');if(window.CB)window.CB.D.set.language=preferred;}});
  }
  window.BenchI18n={t:t,text:text,translate:translate,set:set,showPicker:showPicker,normalize:normalize,resolve:resolve,
    date:function(date,options){return date.toLocaleDateString(language,Object.assign({calendar:'gregory'},options||{}));},
    language:function(){return language},preferred:function(){return preferred}};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',start,{once:true});else start();
})();
