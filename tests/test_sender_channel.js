const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'../realtime_service/index.html'),'utf8');
const fn=src.slice(src.indexOf('function recipientKind('),src.indexOf('function cacheDraft('));
let targetUrl='';
const fields={
 emailFrom:{value:'famesel7@gmail.com'},
 emailSubject:{value:'Отклик: проект / тест'},
 draftText:{value:'Здравствуйте!\nПортфолио https://samsel.site'},
 sendDraftButton:{disabled:false,textContent:''},
 sendDraftHint:{textContent:''}
};
const leads=[{id:'abc',contact:'hiring@example.org',channel:'pending-agency',body:'We are looking for a freelance graphic designer.'}];
const context={URLSearchParams,encodeURIComponent,selected:'abc',leads,localStorage:{setItem:()=>{},getItem:()=>null},
 senderChoices:{},CORPORATE_SENDER:'cco@imon.agency',PERSONAL_SENDER:'famesel7@gmail.com',
 $:key=>fields[key],toast:()=>{},cacheDraft:()=>{},window:{open:(url)=>{targetUrl=url}}};
vm.createContext(context);
vm.runInContext(fn+'\nthis.TEST={foreignLead,senderForLead,changeSender,gmailComposeUrl,yandexComposeUrl,updateSendButton,sendDraft};',context);
const t=context.TEST;
assert.strictEqual(t.senderForLead(leads[0]),'famesel7@gmail.com');
assert.strictEqual(t.senderForLead({id:'ru',channel:'manual-email',body:'Ищем дизайнера для разработки лендинга на Тильде. Нужно оформить несколько экранов, проработать структуру и сделать адаптив.'}),'cco@imon.agency');
assert.strictEqual(t.senderForLead({id:'en',channel:'manual-email',body:'We need a freelance graphic designer to design presentation slides and materials.'}),'famesel7@gmail.com');
const gm=new URL(t.gmailComposeUrl('hiring@example.org','Проект №7','First line\nSecond line'));
assert.strictEqual(decodeURIComponent(gm.pathname),'/mail/u/famesel7@gmail.com/');
assert.strictEqual(gm.searchParams.get('to'),'hiring@example.org');
assert.strictEqual(gm.searchParams.get('su'),'Проект №7');
assert.strictEqual(gm.searchParams.get('body'),'First line\nSecond line');
assert.strictEqual(gm.searchParams.get('tf'),'cm');
const ym=new URL(t.yandexComposeUrl('hiring@example.org','Тема','Привет'));
const mailto=new URL(ym.searchParams.get('mailto'));
assert.strictEqual(ym.host,'mail.yandex.ru');
assert.strictEqual(mailto.protocol,'mailto:');
assert.strictEqual(mailto.searchParams.get('body'),'Привет');
t.updateSendButton(leads[0]);
assert.strictEqual(fields.sendDraftButton.textContent,'✉ Открыть письмо в Gmail');
t.sendDraft();
assert.strictEqual(new URL(targetUrl).host,'mail.google.com');
context.senderChoices['abc']='cco@imon.agency';
fields.emailFrom.value='cco@imon.agency';
t.updateSendButton(leads[0]);
assert.strictEqual(fields.sendDraftButton.textContent,'✉ Открыть письмо в Яндекс Почте');
t.sendDraft();
assert.strictEqual(new URL(targetUrl).host,'mail.yandex.ru');
console.log('PASS: foreign/domestic, manual override, Gmail/Yandex specific compose URLs, Unicode, no send');
