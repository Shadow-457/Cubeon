/* Opt-in live check, synthetic evidence only; never prints secrets/responses. */
const {EventEmitter}=require('node:events');
const fs=require('node:fs');
if(fs.existsSync('.env')) process.loadEnvFile('.env');
const handler=require('../web/api/doctor.js');
const {GROQ_MODELS}=require('../web/assets/doctor-core.js');
if(process.argv.includes('--groq-models')) {
  // Probe each configured Groq model without concealing a failure behind Kilo.
  Promise.all(GROQ_MODELS.map((model,index)=>new Promise((resolve,reject)=>{
    const response=new EventEmitter();response.setHeader=()=>{};
    response.end=text=>{
      response.writableEnded=true;const data=JSON.parse(text);
      if(response.statusCode===200 && data.provider==='groq' && data.model===model) {
        console.log('Groq '+model+': evidence-validated guide accepted');resolve();
      } else {
        console.error('Groq '+model+': HTTP '+response.statusCode+', '+data.error);reject(new Error('live_model_failed'));
      }
    };
    handler.createHandler({env:{GROQ_API_KEY:process.env.GROQ_API_KEY},chooseModel:()=>index})(
      {method:'POST',headers:{origin:'https://cubeon.ylet.online','content-type':'application/json'},
        body:{log:'java.lang.OutOfMemoryError: Java heap space',version:'1.21'}},response).catch(reject);
  }))).catch(()=>{process.exitCode=1;});
} else {
const response=new EventEmitter();
response.setHeader=()=>{};
response.end=text=>{
  response.writableEnded=true;
  const data=JSON.parse(text);
  if(response.statusCode!==200 || data.source!=='ai') {
    console.error('Doctor live check failed, HTTP '+response.statusCode);process.exitCode=1;
  } else console.log('Doctor live check passed: '+data.provider+', evidence and Markdown steps accepted.');
};
handler({method:'POST',headers:{origin:'https://cubeon.ylet.online','content-type':'application/json'},
  body:{log:'java.lang.OutOfMemoryError: Java heap space',version:'1.21'}},response).catch(()=>{console.error('Live check could not complete.');process.exitCode=1;});
}
