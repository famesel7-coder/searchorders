'use strict';
const assert = require('node:assert/strict');
const {test}=require('node:test');
const {idFrom}=require('../tools/hh-isolated-browser.js');

test('recognizes official numeric vacancy IDs',()=>{
  assert.equal(idFrom('138711751'),'138711751');
  assert.equal(idFrom('https://spb.hh.ru/vacancy/138711751?from=search'),'138711751');
  assert.equal(idFrom('https://hh.ru/vacancy/138711751'),'138711751');
  assert.equal(idFrom('https://www.hh.ru/vacancy/138711751/'),'138711751');
  assert.equal(idFrom('https://hh.ru:443/vacancy/138711751'),'138711751');
});
test('rejects other domains, protocols, credentials, and paths',()=>{
  for(const s of [
    'http://hh.ru/vacancy/138711751',
    'https://hh.ru.evil.test/vacancy/138711751',
    'https://evil.test/vacancy/138711751',
    'https://user:secret@hh.ru/vacancy/138711751',
    'https://hh.ru/applicant/resumes',
    'https://hh.ru/vacancy/123/extra',
    'javascript:alert(1)', '../138711751', '0', '', '999'
  ])assert.equal(idFrom(s),null,s);
});
test('does not require Puppeteer just to parse an ID',()=>{
  assert.equal(typeof idFrom,'function');
});
