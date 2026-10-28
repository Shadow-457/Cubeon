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
  assert.equal(D.localDiagnosis('EXCEPTION_ACCESS_VIOLATION').category,'unknown');
  const missing = D.localDiagnosis("Mod 'Example Mod' requires fabric-api, which is missing!");
  assert.match(missing.cause,/Example Mod.*fabric-api/);
  assert.match(missing.steps.find(s => s.action === 'repair').instruction,/\*\*fabric-api\*\*/);
  const fabric = D.localDiagnosis("Mod 'Sodium' (sodium) 0.5 requires version 0.91 or later of mod 'Fabric API' (fabric-api), which is missing!");
  assert.match(fabric.cause,/Sodium.*Fabric API/);
  assert.match(D.localDiagnosis('Unrecognized VM option Bogus').steps[0].instruction,/\*\*Bogus\*\*/);
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
  assert.equal(calls[0].url,'/api/doctor');
  assert.equal(JSON.parse(calls[0].options.body).version,'1.21');
  assert.equal(calls[0].options.headers.Authorization,undefined);
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:429})}),/rate_limited/);
  await assert.rejects(D.analyzeViaEndpoint(log,{}, {fetch:async()=>({ok:false,status:503})}),/ai_unavailable/);
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
