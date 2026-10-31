#!/usr/bin/env node
'use strict';
// SearchOrders HH: private persistent Chrome profile, entirely headless except
// one-time user-driven login. Never uses screen capture, AppleScript, OS clicks,
// shared Chrome tabs, or the account's default Chrome profile.
const fs=require('node:fs'), os=require('node:os'), path=require('node:path');
const runtime=path.resolve(__dirname,'../.runtime');
const lockPath=path.join(runtime,'hh-agent.lock');
const profile=path.join(os.homedir(),'Library','Application Support','SearchOrders-HH-Agent');
const chrome='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';

function idFrom(input) {
  if (/^[1-9][0-9]{5,14}$/.test(input||'')) return input;
  try {
    const u=new URL(input);
    if (u.protocol!=='https:'||!['hh.ru','spb.hh.ru','www.hh.ru'].includes(u.hostname)
        ||u.username||u.password||u.port)return null;
    return u.pathname.match(/^\/vacancy\/([1-9][0-9]{5,14})\/?$/)?.[1]||null;
  }catch{return null}
}
function print(x){process.stdout.write(JSON.stringify(x,null,2)+'\n')}
function sleep(n){return new Promise(r=>setTimeout(r,n))}
function puppeteer(){
  const opts=[process.env.SEARCHORDERS_PUPPETEER_MODULE,'puppeteer','puppeteer-core',
    path.join(runtime,'hh-agent-deps/node_modules/puppeteer-core')].filter(Boolean);
  const cache=path.join(os.homedir(),'.npm/_npx');
  if(fs.existsSync(cache))for(const p of fs.readdirSync(cache))
    opts.push(path.join(cache,p,'node_modules/puppeteer'));
  for(const o of opts)try{return require(o)}catch(e){
    if(!['MODULE_NOT_FOUND','ERR_MODULE_NOT_FOUND'].includes(e.code))throw e
  }
  throw Error('Puppeteer unavailable. Install: npm install --prefix .runtime/hh-agent-deps puppeteer-core');
}
function lock(){
  fs.mkdirSync(runtime,{recursive:true,mode:0o700});
  try{
    const fd=fs.openSync(lockPath,'wx',0o600);
    fs.writeSync(fd,JSON.stringify({pid:process.pid,at:new Date().toISOString()}));fs.closeSync(fd);
  }catch(e){
    if(e.code!=='EEXIST')throw e;
    let owner;
    try{owner=JSON.parse(fs.readFileSync(lockPath,'utf8'))}catch{throw Error('Invalid lock. Check hh-agent.lock')}
    if(owner.pid){
      try{process.kill(owner.pid,0);throw Error('Another HH automation already owns the profile (PID '+owner.pid+')')}
      catch(x){if(x.code!=='ESRCH')throw x}
    }
    fs.unlinkSync(lockPath);
    return lock();
  }
  return ()=>{try{if(JSON.parse(fs.readFileSync(lockPath)).pid===process.pid)fs.unlinkSync(lockPath)}catch{}}
}
async function browser(headless=true){
  fs.mkdirSync(profile,{recursive:true,mode:0o700});fs.chmodSync(profile,0o700);
  return puppeteer().launch({executablePath:chrome,headless,userDataDir:profile,
    defaultViewport:{width:1400,height:900},
    args:['--no-first-run','--no-default-browser-check','--disable-extensions',
    '--disable-background-networking','--disable-dev-shm-usage']});
}
async function visit(page,url){
  const res=await page.goto(url,{waitUntil:'domcontentloaded',timeout:30000});
  await sleep(500);
  const data=await page.evaluate(()=>({title:document.title,h1:document.querySelector('h1')?.innerText?.trim()||'',
    text:(document.body?.innerText||'').slice(0,7500)}));
  return {...data,url:page.url(),http:res?.status()||null}
}
function blocked(i){return [403,429].includes(i.http)||/captcha|не робот|проверка безопасности|доступ ограничен/i.test(i.title+' '+i.text)}
async function status(b){
  const p=await b.newPage();
  try{
    const i=await visit(p,'https://spb.hh.ru/applicant/resumes');
    const auth=i.http===200&&i.url.includes('/applicant/resumes')&&!blocked(i)
      && !/войти или зарегистрироваться|войти в аккаунт/i.test(i.text);
    return {kind:'status',authenticated:auth,challenge:blocked(i),loginRequired:!auth&&!blocked(i),
      http:i.http,url:i.url,headless:true};
  }finally{await p.close()}
}
async function check(b,id){
  const p=await b.newPage();
  try{
    const i=await visit(p,'https://spb.hh.ru/vacancy/'+id);
    return {kind:'check',id,title:i.h1,http:i.http,challenge:blocked(i),
      state:blocked(i)?'blocked':/вы откликнулись/i.test(i.text)?'already_applied':
      /откликнуться/i.test(i.text)?'possible_to_apply':'unknown',submitted:false};
  }finally{await p.close()}
}
async function visibleText(p,css,text){
  for(const x of await p.$$(css)){
    const pass=await x.evaluate((n,text)=>{
      const r=n.getBoundingClientRect();
      return r.width>0&&r.height>0&&(n.innerText||'').trim().includes(text);
    },text);
    if(pass)return x;
  }
  return null;
}
async function apply(b,id,resume,letter){
  if(!resume||letter.length<100||letter.length>4000)throw Error('Missing resume or valid personal cover letter');
  const auth=await status(b);
  if(!auth.authenticated)return {kind:'apply',id,state:auth.challenge?'hh_access_blocked':'login_required',submitted:false};
  const p=await b.newPage();
  try{
    const v=await visit(p,'https://spb.hh.ru/vacancy/'+id);
    if(blocked(v))return {kind:'apply',id,state:'blocked',submitted:false};
    if(/вы откликнулись/i.test(v.text))return {kind:'apply',id,state:'already_applied',submitted:false};
    if(!v.h1||v.http!==200)return {kind:'apply',id,state:'vacancy_not_verified',submitted:false};
    let btn=await p.$('[data-qa="vacancy-response-link-top"]');
    if(!btn)btn=await visibleText(p,'button,a','Откликнуться');
    if(!btn)return {kind:'apply',id,state:'apply_button_not_found',submitted:false};
    await btn.click();await sleep(800);
    const screen=await p.evaluate(()=>document.body?.innerText||'');
    if(/вопросы работодателя|ответьте на вопросы/i.test(screen))
      return {kind:'apply',id,state:'custom_questions_need_review',submitted:false};
    // Work only with a verified resume. An unfamiliar UI always fails closed.
    const resumeText=await p.evaluate(()=>[...document.querySelectorAll('[data-qa]')]
      .filter(n=>(n.getAttribute('data-qa')||'').includes('resume'))
      .map(n=>(n.innerText||'').trim()).filter(Boolean).join(' | '));
    if(!resumeText.includes(resume))
      return {kind:'apply',id,state:'correct_resume_not_verified',requested:resume,submitted:false};
    let field=await p.$('textarea');
    if(!field){
      const open=await visibleText(p,'button,[role="button"]','Сопроводительное письмо');
      if(open){await open.click();await sleep(250);field=await p.$('textarea')}
    }
    if(!field)return {kind:'apply',id,state:'cover_field_not_found',submitted:false};
    await field.type(letter,{delay:1});
    if(await field.evaluate(el=>el.value)!==letter)
      return {kind:'apply',id,state:'letter_not_verified',submitted:false};
    let send;
    for(const x of await p.$$('button,[role="button"]')){
      const t=await x.evaluate(n=>(n.innerText||'').trim());
      if(t==='Отправить'){send=x;break}
    }
    if(!send)return {kind:'apply',id,state:'submit_button_not_found',submitted:false};
    await send.click();await sleep(900);
    let ok=/вы откликнулись|отклик отправлен/i.test(await p.evaluate(()=>document.body?.innerText||''));
    if(!ok){
      const next=await visit(p,'https://spb.hh.ru/vacancy/'+id);
      ok=/вы откликнулись/i.test(next.text);
    }
    return {kind:'apply',id,state:ok?'confirmed_sent':'unconfirmed_check_before_retry',submitted:ok,resume};
  }finally{await p.close()}
}
async function main(){
  const [command='help',value,...options]=process.argv.slice(2);
  if(command==='help'){
    return print({commands:['doctor','status','check HH_VACANCY_ID_OR_URL','login (one-time manual)',
      'apply ID --resume NAME --letter-file /absolute/letter.txt'],
      sharedDesktopInput:false,privateProfile:profile})
  }
  if(!['doctor','status','check','login','apply'].includes(command))throw Error('Invalid command');
  if(!fs.existsSync(chrome))throw Error('Chrome missing');
  const unlock=lock();let b;
  try{
    b=await browser(command!=='login');
    if(command==='doctor'){
      const p=await b.newPage(),res=await visit(p,'https://example.com');
      await p.close();
      print({kind:'doctor',headless:true,profileIsSeparate:true,screenCapture:false,
        systemMouseKeyboard:false,available:res.http===200,http:res.http,title:res.title})
    }else if(command==='status')print(await status(b));
    else if(command==='login'){
      const p=await b.newPage();
      await p.goto('https://spb.hh.ru/applicant/resumes',{waitUntil:'domcontentloaded'});
      print({kind:'login',instructions:'Sign in yourself in the SEPARATE HH window, then close that window.'});
      await new Promise(done=>b.on('disconnected',done))
    }else{
      const id=idFrom(value);
      if(!id)throw Error('Not an official HH vacancy URL or numeric ID');
      if(command==='check')print(await check(b,id));
      else{
        const j={};for(let i=0;i<options.length;i+=2)j[options[i]]=options[i+1];
        if(!j['--resume']||!j['--letter-file'])throw Error('Need --resume and --letter-file');
        const letter=fs.readFileSync(path.resolve(j['--letter-file']),'utf8').trim();
        print(await apply(b,id,j['--resume'],letter))
      }
    }
  }finally{if(b?.connected)await b.close();unlock()}
}
if(require.main===module)main().catch(e=>{print({ok:false,error:e.message});process.exitCode=1});
module.exports={idFrom};
