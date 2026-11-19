import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import {translate} from '../src/lib/translation.ts';
import {german} from '../src/lib/messages/de.ts';

test('translations preserve fallback content, spacing, interpolation and plain text',()=>{
  assert.equal(translate('de',' Edit '),' Bearbeiten ');
  assert.equal(translate('en','Edit'),'Edit');
  assert.equal(translate('de','custom exercise name'),'custom exercise name');
  assert.equal(translate('de','constructor'),'constructor');
  assert.equal(translate('de','Type {username} to confirm',{username:'<student>$&'}),'Zur Bestätigung <student>$& eingeben');
  assert.equal(translate('en','Count: {count}',{count:0}),'Count: 0');
});
test('literal translation calls have German catalog entries',()=>{
  const root=new URL('../src/',import.meta.url),missing=new Set<string>();let checked=0;
  for(const file of fs.readdirSync(root,{recursive:true}).filter(file=>file.endsWith('.tsx'))){
    const source=fs.readFileSync(new URL(file,root),'utf8');
    for(const match of source.matchAll(/\bt\(("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')/g)){
      const literal=match[1];
      const message=(literal[0]==='"'?JSON.parse(literal):literal.slice(1,-1).replace(/\\(['\\])/g,'$1')).trim();
      if(!/[a-zA-Z]/.test(message))continue;
      checked++;if(!Object.hasOwn(german,message))missing.add(message);
    }
  }
  assert.ok(checked>500);assert.deepEqual([...missing],[]);
});
