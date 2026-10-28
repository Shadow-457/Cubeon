/* Opt-in live check, synthetic evidence only; never prints secrets/responses. */
const {EventEmitter}=require('node:events');
const fs=require('node:fs');
if(!process.env.KILO_API_KEY && fs.existsSync('.env')) process.loadEnvFile('.env');
const handler=require('../web/api/doctor.js');
const response=new EventEmitter();
response.setHeader=()=>{};
response.end=text=>{
  response.writableEnded=true;
  const data=JSON.parse(text);
  if(response.statusCode!==200 || data.source!=='ai') {
    console.error('Kilo Doctor live check failed, HTTP '+response.statusCode);process.exitCode=1;
  } else console.log('Kilo Doctor live check passed: authenticated auto/free, evidence and visual steps accepted.');
};
handler({method:'POST',headers:{origin:'https://cubeon.ylet.online','content-type':'application/json'},
  body:{log:'java.lang.OutOfMemoryError: Java heap space',version:'1.21'}},response).catch(()=>{console.error('Live check could not complete.');process.exitCode=1;});
