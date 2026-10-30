import assert from 'node:assert/strict';
import { test } from 'node:test';
import { duration, external, image, number, row, rows, safeNext, truth } from '../src/lib/data.ts';

test('redirects stay on this origin and reject backslashes and protocol-relative targets', () => {
  for (const next of ['https://evil.invalid','//evil.invalid','/\\evil.invalid','/login','/signup']) assert.equal(safeNext(next), '/dashboard');
  assert.equal(safeNext('/challenge?id=4'), '/challenge?id=4');
});
test('untrusted image and social URLs cannot become executable URLs', () => {
  for (const url of ['javascript:alert(1)','data:text/html,evil','//evil.invalid/image','/\\evil.invalid']) assert.equal(image(url),'/assets/images/ctf-default.png');
  assert.equal(external('javascript:alert(1)'),undefined);
  assert.equal(external('https://example.org'),'https://example.org/');
});
test('legacy boolean and numeric encodings normalize without truthy string mistakes', () => {
  for(const value of [false,'false','f','0',null,undefined]) assert.equal(truth(value),false);
  for(const value of [true,'true','t',1,'1']) assert.equal(truth(value),true);
  assert.equal(number('not a number'),0);assert.equal(duration(3661),'01:01:01');assert.equal(duration(-3),'00:00:00');
});
test('invalid collection payloads stay empty and cannot crash page rendering',()=>{
  assert.deepEqual(row(null),{});assert.deepEqual(row([]),{});assert.deepEqual(rows('wrong'),[]);
});
