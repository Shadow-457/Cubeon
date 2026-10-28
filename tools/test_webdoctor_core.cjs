/* Offline rule, evidence, failover, safety and cancellation checks. */
const assert = require('node:assert/strict');
const D = require('../web/assets/doctor-core.js');
async function main() {
  const scenarios = [
    ['OutOfMemoryError: Java heap space','memory'],
    ['UnsupportedClassVersionError: BadClass','java'],
    ['Unrecognized VM option Bogus','flags'],
    ['Found duplicate mods: example','mods'],
    ['Example requires fabric-api, which is missing','dependencies'],
    ['GLFW error 65542: WGL: failed','graphics'],
    ['java.nio.file.AccessDeniedException: file','storage'],
    ['java.net.UnknownHostException: example','network'],
    ['Failed to verify username','session'],
    ['MixinApplyError: example','mods'],
    ['Process exited with code 1','unknown']
  ];
  for (const [log, category] of scenarios) {
    const result = D.localDiagnosis(log);
    assert.equal(result.category,category);
    result.steps.forEach(s => assert.ok(D.ACTIONS[s.action]));
    result.evidence.forEach(e => assert.ok(log.includes(e)));
  }
  const native = D.localDiagnosis('EXCEPTION_ACCESS_VIOLATION');
  assert.equal(native.category,'native');
  assert.equal(native.confidence,'low');
  assert.ok(native.steps.every(s => s.action === 'log'), 'Native exit alone must not blame a GPU, Java version or mod');
  const missing = D.localDiagnosis("Mod 'Example Mod' requires fabric-api, which is missing!");
  assert.match(missing.cause,/Example Mod.*fabric-api/);
  assert.match(missing.steps.find(s => s.action === 'repair').instruction,/\*\*fabric-api\*\*/);
  const fabric = D.localDiagnosis("Mod 'Sodium' (sodium) 0.5 requires version 0.91 or later of mod 'Fabric API' (fabric-api), which is missing!");
  assert.match(fabric.cause,/Sodium.*Fabric API/);
  assert.match(D.localDiagnosis('Unrecognized VM option Bogus').steps[0].instruction,/\*\*Bogus\*\*/);
  const fixtures = [
    {log:"[main/INFO]: Loading 80 mods:\n - innocentmod 1.0\njava.lang.RuntimeException: Could not execute entrypoint stage 'client' due to errors, provided by 'betterclouds' at 'com.example.Client'!\nCaused by: java.lang.NoSuchMethodError: net.minecraft.class_310.foo()",
      category:'mods', yes:['betterclouds','Switch off **betterclouds**','re-enable'], no:['innocentmod']},
    {log:'Mixin apply for mod iris failed iris.mixins.json:GameRendererMixin -> net.minecraft.GameRenderer: InvalidMixinException',
      category:'mods', yes:['iris','Switch off **iris**'], no:['mod named in the error']},
    {log:'MixinApplyError: mixins.widgets.json:ExampleMixin\nCaused by: ClassNotFoundException: com.widgets.SomeClass',
      category:'mods', yes:['mixins.widgets.json','no confirmed mod to disable'], no:['Switch off **widgets**']},
    {log:'java.lang.NoClassDefFoundError: com.example.SomeClass',
      category:'classes', yes:['Check & repair','class package alone'], no:['Switch off']},
    {log:'Failed to create mod instance. ModID: examplemod, class com.example.Example',
      category:'mods', yes:['examplemod','Switch off **examplemod**']},
    {log:'net.neoforged.fml.ModLoadingException: Loading errors encountered\n-- MOD example --\nMod File: C:\\game\\mods\\example-1.4.jar\nMod Name: Example Mod\nFailure message: Example Mod has failed to load correctly\n-- System Details --\nMod List:\n othermod.jar | Other Mod | othermod',
      category:'mods', yes:['Example Mod (example)','example-1.4.jar'], no:['othermod']},
    {log:"[main/INFO]: Mod 'Innocent' is loaded\nMod 'More Culling' (moreculling) 0.2 requires version 8 or later of mod 'Cloth Config' (cloth-config), which is missing!\nMod 'Iris' (iris) 1.7 requires version 0.5 of mod 'Sodium' (sodium), but only the wrong version is present: 0.4!",
      category:'dependencies', yes:['More Culling (moreculling)','Cloth Config (cloth-config)','Sodium (sodium)','version 8','version 0.5'], no:['Innocent','Switch off']},
    {log:"Mod 'Sodium' (sodium) 0.8 is incompatible with version 1.10 or earlier of mod 'Iris' (iris), yet a conflicting version is present: 1.10",
      category:'dependencies', yes:['conflicts with','switch off **Iris (iris)**','re-enable']},
    {log:'Missing or unsupported mandatory dependencies:\nMod ID: cloth_config, Requested by: examplemod, Expected range: [8.0,), Actual version: [MISSING]',
      category:'dependencies', yes:['examplemod','cloth_config','Required version: `[8.0,)`'], no:['Switch off']},
    {log:"Mod 'Example' (example) requires version 1.21 of mod 'Minecraft' (minecraft), but only 1.20.1 is present",
      category:'dependencies', yes:['Minecraft','New instance'], no:['Install or repair Minecraft']},
    {log:'Mod examplemod requires neoforge 21.1.0 or above\nCurrently, neoforge is 21.0.0',
      category:'dependencies', yes:['neoforge','New instance'], no:['Install or repair neoforge']},
    {log:"Mod 'Example' requires Java 21, but only Java 17 is present",
      category:'java', yes:['Java 21'], no:['Install or repair Java']},
    {log:'java.lang.UnsupportedClassVersionError: BadClass has been compiled by a more recent version (class file version 65.0), this runtime recognizes up to 61.0',
      category:'java', yes:['Java 21'], no:['Switch off']},
    {log:"Could not execute entrypoint stage 'client', provided by 'examplemod'\nCaused by: OutOfMemoryError: Java heap space",
      category:'memory', yes:['Allocated RAM'], no:['Switch off']},
    {log:'OutOfMemoryError: unable to create native thread',
      category:'native-memory', yes:['lower it','Increasing the heap can make'], no:['Increase Allocated RAM']},
    {log:'Native memory allocation (malloc) failed to allocate 1048576 bytes',
      category:'native-memory', yes:['lower it'], no:['Increase Allocated RAM']},
    {log:'Invalid maximum heap size: -Xmx900000G', category:'flags', yes:['-Xmx','Copy your custom flags']},
    {log:'java.util.zip.ZipException: zip END header not found in badmod-1.2.jar',
      category:'corrupt', yes:['badmod-1.2.jar','disable it for a test'], no:['archive “java.util.zip”']},
    {log:'java.util.zip.ZipException: invalid LOC header', category:'corrupt', no:['archive “java.util.zip”']},
    {log:'Failed to parse config/example.json\ncom.google.gson.JsonSyntaxException: Expected name at line 8',
      category:'config', yes:['config/example.json','.backup','restore the original filename']},
    {log:'Could not find or load main class net.fabricmc.loader.impl.launch.knot.KnotClient',
      category:'installation', yes:['installation checks','complete installation and game logs'], no:['remove the rejected option']},
    {log:'java.lang.UnsatisfiedLinkError: wrong ELF class: ELFCLASS32',
      category:'java', yes:['architecture'], no:['graphics-driver update']},
    {log:'java.lang.StackOverflowError\n at com.example.Recurse.go(Recurse.java:10)',
      category:'stack', yes:['repeating stack trace'], no:['Increase Allocated RAM']},
    {log:'java.nio.file.AccessDeniedException: config/example.json\ncom.google.gson.JsonParseException: could not read configuration',
      category:'storage', yes:['free disk space'], no:['.backup suffix']},
    {log:'java.net.SSLHandshakeException: PKIX path building failed', category:'network', yes:['date and time','certificate verification']},
    {log:'java.lang.NullPointerException: Rendering overlay\nSuspected Mods:\n    Example Overlay (exampleoverlay), Version: 1.4\n-- System Details --\nMod List:\n    other.jar | Innocent (innocent)',
      category:'mods', yes:['Example Overlay (exampleoverlay)','Switch off'], no:['Innocent']},
    {log:"[main/WARN]: Mod 'Innocent' recommends mod 'Optional API', which is missing\n[main/INFO]: OpenGL 4.6\nProcess exited with code 1",
      category:'unknown', no:['Innocent','Optional API','graphics driver']},
    {log:"Mixin apply for mod examplemod failed\nMod 'innocentmod' 1.0 is loaded\nCaused by: NoSuchFieldError: missingField",
      category:'mods', yes:['examplemod'], no:['innocentmod']},
    {log:"Found duplicate mods:\n- Mod ID: 'sodium' from mod files: sodium-1.jar, sodium-2.jar",
      category:'mods', yes:['sodium','extra copies']},
    {log:"Mixin apply for mod iris failed\nMixin apply for mod sodium failed", category:'mods',
      yes:['iris','sodium','one of these mods at a time','re-enable'], no:['Switch off **iris**']},
    {log:'[main/INFO]: Unrecognized VM option HarmlessExample\nUnrecognized VM option ActualRejectedFlag',
      category:'flags', yes:['ActualRejectedFlag'], no:['HarmlessExample']},
    {log:'[main/INFO]: class file version 52.0\nUnsupportedClassVersionError: Example (class file version 65.0)',
      category:'java', yes:['Java 21'], no:['Java 8']},
    {log:'java.lang.NullPointerException: Rendering overlay\nSuspected Mods: NONE\nMod List:\n example.jar | Innocent (innocent)',
      category:'unknown', no:['Innocent','Switch off']}
  ];
  for (const fixture of fixtures) {
    const result = D.localDiagnosis(fixture.log);
    const advice = JSON.stringify({cause:result.cause, steps:result.steps});
    assert.equal(result.category,fixture.category,fixture.log);
    for (const phrase of fixture.yes || []) assert.ok(advice.includes(phrase),phrase + ': ' + advice);
    for (const phrase of fixture.no || []) assert.ok(!advice.includes(phrase),phrase + ': ' + advice);
    assert.ok(result.steps.length <= 6);
    assert.ok(result.evidence.length || fixture.category === 'unknown');
    result.evidence.forEach(e => assert.ok(fixture.log.includes(e),e));
    result.steps.forEach(s => assert.ok(D.ACTIONS[s.action]));
  }
  const many = D.localDiagnosis(Array.from({length:500},(_,i) => `Mod 'Example ${i}' requires dependency${i}, which is missing!`).join('\n'));
  assert.equal(many.steps.length,6,'Long conflict lists must remain a manageable guide');
  const hostile = D.localDiagnosis('x'.repeat(64000));
  assert.equal(hostile.category,'unknown');
  const privateLog = '--accessToken hidden --username alice Authorization: Bearer xyz\nC:\\Users\\Alice\\file /home/bob/game a@b.com';
  assert.doesNotMatch(D.redactLog(privateLog),/hidden|alice|xyz|bob|a@b.com/i);
  assert.equal(D.excerpt('x'.repeat(70000)).length,64000);
  const log = 'java.lang.OutOfMemoryError: Java heap space';
  const data = {cause:'Heap exhausted',confidence:'high',evidence:[log],
    steps:[{action:'memory',title:'Raise memory',instruction:'Use the safe RAM slider.'}],verify:'Launch once',rollback:'Restore the previous value'};
  assert.equal(D.parseDiagnosis('```json\n'+JSON.stringify(data)+'\n```',log).cause,data.cause);
  assert.equal(D.parseDiagnosis({message:{content:[{type:'text',text:JSON.stringify(data)}]}},log).confidence,'high');
  assert.throws(()=>D.parseDiagnosis(JSON.stringify({...data,evidence:['invented']}),log));
  assert.throws(()=>D.parseDiagnosis(JSON.stringify({...data,steps:[{action:'delete',title:'bad',instruction:'bad'}]}),log));
  assert.throws(()=>D.parseDiagnosis('not json',log));
  for(const instruction of ['delete all worlds','**delete** all **worlds**','delete **auth_key**','powershell run','disable your firewall','**disable** your `firewall`','Download https://evil.example']) {
    assert.throws(()=>D.parseDiagnosis(JSON.stringify({...data,steps:[{action:'mods',title:'bad',instruction}]}),log));
  }
  const calls=[];
  const fetcher=async(url,options)=>{
    calls.push({url,options});
    return {ok:true,json:async()=>data};
  };
  const result = await D.analyzeViaEndpoint(log,{version:'1.21'}, {fetch:fetcher});
  assert.equal(result.model,'Kilo auto/free');
  for (const model of D.GROQ_MODELS) {
    const groq=await D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:true,json:async()=>({...data,provider:'groq',model})})});
    assert.equal(groq.provider,'groq');assert.equal(groq.model,model);
  }
  assert.equal(calls[0].url,'/api/doctor');
  assert.equal(JSON.parse(calls[0].options.body).version,'1.21');
  assert.equal(calls[0].options.headers.Authorization,undefined);
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:429})}),/rate_limited/);
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:503})}),/ai_unavailable/);
  for(const reason of ['ai_not_configured','ai_credentials_invalid','ai_quota_exhausted','ai_timeout','ai_bad_response','ai_provider_unavailable','ai_request_rejected']) {
    await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:503,json:async()=>({error:reason})})}),new RegExp(reason));
  }
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:503,json:async()=>({error:'secret-provider-text'})})}),/ai_unavailable/);
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:503,json:async()=>({error:'ai_credentials_invalid',provider:'groq'})})}),
    error=>error.provider==='groq' && error.message==='ai_credentials_invalid');
  let aborted=false;
  await assert.rejects(D.withTimeout(signal=>new Promise(()=>signal.addEventListener('abort',()=>{aborted=true;})),10),/request_timeout/);
  assert.ok(aborted);
  const controller=new AbortController();controller.abort();
  let started=false;
  await assert.rejects(D.withTimeout(()=>{started=true;},100,controller.signal),/cancelled/);
  assert.equal(started,false);
  const live=new AbortController();
  const pending=D.withTimeout(()=>new Promise(()=>{}),1000,live.signal); live.abort();
  await assert.rejects(pending,/cancelled/);
  console.log('Doctor core: rules, redaction, evidence, same-origin AI and cancel passed');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
