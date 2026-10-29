const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const html=fs.readFileSync(path.join(__dirname,'../realtime_service/index.html'),'utf8');
const js=html.slice(html.indexOf('function recipientKind('),html.indexOf('function cacheDraft('));
const sent=[];
let openedUrl=null;
const fields={
 emailFrom:{value:'famesel7@gmail.com'},
 emailSubject:{value:'Freelance Presentation Designer'},
 draftText:{value:'Hello,\n\nI am an independent designer. Portfolio: https://samsel.site\n\nBest regards, Vyacheslav'},
 sendDraftButton:{disabled:false,textContent:''},
 sendDraftHint:{textContent:''}
};
const lead={
 id:'a'.repeat(20),contact:'hiring@example.org',
 channel:'pending-agency',body:'Freelance presentation design project with a detailed brief.',
 contacted:0
};
const choices={};
const ctx={
 URLSearchParams,encodeURIComponent,leads:[lead],selected:lead.id,
 CORPORATE_SENDER:'cco@imon.agency',PERSONAL_SENDER:'famesel7@gmail.com',
 senderChoices:choices,localStorage:{setItem:()=>{},getItem:()=>null},
 $:key=>fields[key],toast:()=>{},cacheDraft:()=>{},
 window:{open:(url,target,options)=>{openedUrl=url;assert.strictEqual(target,'_blank');sent.push(url)}}
};
vm.createContext(ctx);
vm.runInContext(js+'\nthis.helpers={foreignLead,senderForLead,changeSender,gmailComposeUrl,yandexComposeUrl,updateSendButton,sendDraft,openSelectedMailbox};',ctx);
const h=ctx.helpers;

assert.strictEqual(h.senderForLead(lead),'famesel7@gmail.com');
assert.strictEqual(h.senderForLead({
 id:'b'.repeat(20),channel:'manual-email',
 body:'Ищем дизайнера для сайта и адаптива. Требуется сделать лендинг на Tilda, выполнить несколько экранов и подготовить макеты.'
}),'cco@imon.agency');

const url=new URL(h.gmailComposeUrl('hiring@example.org','Тема / тест 2026','First line\nSecond line'));
assert.strictEqual(url.origin,'https://mail.google.com');
assert.strictEqual(url.pathname,'/mail/');
assert.strictEqual(url.searchParams.get('view'),'cm');
assert.strictEqual(url.searchParams.get('fs'),'1');
assert.strictEqual(url.searchParams.get('to'),'hiring@example.org');
assert.strictEqual(url.searchParams.get('su'),'Тема / тест 2026');
assert.strictEqual(url.searchParams.get('body'),'First line\nSecond line');
assert(!url.pathname.includes('/u/'),'No account-specific Gmail route (404 regression)');
assert(!url.searchParams.has('tf'),'Do not construct Gmail internal redirect manually');

h.updateSendButton(lead);
assert.strictEqual(fields.sendDraftButton.textContent,'✉ Открыть готовое письмо в Gmail');
h.sendDraft();
let ready=new URL(openedUrl);
assert.strictEqual(ready.pathname,'/mail/');
assert.strictEqual(ready.searchParams.get('to'),'hiring@example.org');
assert.strictEqual(ready.searchParams.get('su'),fields.emailSubject.value);
assert.strictEqual(ready.searchParams.get('body'),fields.draftText.value);
assert.strictEqual(lead.contacted,0,'Opening draft does not mean the email was sent');
assert.strictEqual(sent.length,1,'One click opens one draft');

ctx.senderChoices[lead.id]='cco@imon.agency';
fields.emailFrom.value='cco@imon.agency';
h.updateSendButton(lead);
assert.strictEqual(fields.sendDraftButton.textContent,'✉ Открыть готовое письмо в Яндекс Почте');
h.sendDraft();
assert.strictEqual(new URL(openedUrl).host,'mail.yandex.ru');
assert.strictEqual(sent.length,2);
assert.strictEqual(lead.contacted,0);

ctx.senderChoices[lead.id]='famesel7@gmail.com';
fields.emailFrom.value='famesel7@gmail.com';
h.openSelectedMailbox();
assert.strictEqual(openedUrl,'https://mail.google.com/');
assert(!html.includes('gmailAppPassword'));
assert(!html.includes('/api/gmail/send'));
console.log('PASS: Gmail prefilled draft, Unicode fields, manual send, Yandex, no 404 account URL');
