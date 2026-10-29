const fs=require('fs'),vm=require('vm'),assert=require('assert'),path=require('path');
const src=fs.readFileSync(path.join(__dirname,'../realtime_service/index.html'),'utf8');
const snippet=src.slice(src.indexOf('function looksEnglish('),src.indexOf('function renderDetails(){'));
const original='Transparency International is looking for freelance designers for publication layouts. '+ 'The project requires visual communication and editorial design.';
const translation='Transparency International ищет дизайнеров-фрилансеров для оформления публикаций.';
const lead={id:'z'.repeat(20),body:original};
const field={textContent:'',lang:''};
const note={hidden:true,textContent:''};
const ruButton={disabled:false,dataset:{lang:'ru'},classList:{toggle(){ }},setAttribute(){ }};
const enButton={disabled:false,dataset:{lang:'en'},classList:{toggle(){ }},setAttribute(){ }};
const ctx={leads:[lead],selected:lead.id,translations:{},translationLanguage:{},translationPending:{},
 $:id=>({projectDescription:field,translationStatus:note,translateRussian:ruButton}[id]),
 document:{querySelectorAll:()=>[ruButton,enButton]},
 api:async (_path,payload)=>{assert.strictEqual(_path,'/api/translate');assert.strictEqual(payload.id,lead.id);return {translation}},
 toast:()=>{},console};
vm.createContext(ctx);
vm.runInContext(snippet+';this.test={looksEnglish,displayTranslation,switchTranslation}',ctx);
(async()=>{
 assert(ctx.test.looksEnglish(original));
 assert(!ctx.test.looksEnglish('Нужен дизайнер для разработки нескольких слайдов и презентации'));
 ctx.test.displayTranslation(lead,'en');
 assert.strictEqual(field.textContent,original);
 await ctx.test.switchTranslation('ru');
 assert.strictEqual(field.textContent,translation);
 assert.strictEqual(field.lang,'ru');
 assert(!note.hidden);
 await ctx.test.switchTranslation('en');
 assert.strictEqual(field.textContent,original);
 assert.strictEqual(field.lang,'en');
 await ctx.test.switchTranslation('ru');
 assert.strictEqual(field.textContent,translation);
 console.log('PASS: English/Russian toggle, original preserved, translation cached');
})().catch(err=>{console.error(err);process.exitCode=1});
