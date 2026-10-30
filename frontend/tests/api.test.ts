import assert from 'node:assert/strict';
import { beforeEach, test } from 'node:test';
import { ApiError, request, setCsrf } from '../src/lib/api.ts';

beforeEach(()=>{setCsrf('fixture-csrf-token');});
test('mutations include the in-memory CSRF token and same-origin cookies',async()=>{
  let captured:RequestInit|undefined;
  globalThis.fetch=async(_url,options)=>{captured=options;return Response.json({success:true});};
  const form=new FormData();form.set('username','fixture');
  await request('/backend/login.php',{method:'POST',body:form});
  assert.equal(captured?.credentials,'same-origin');assert.equal(form.get('csrf_token'),'fixture-csrf-token');
  assert.equal((captured?.headers as Record<string,string>)['X-CSRF-Token'],'fixture-csrf-token');
  assert.equal((captured?.headers as Record<string,string>)['Content-Type'],undefined);
});
test('a failed mutation is never automatically retried',async()=>{
  let attempts=0;globalThis.fetch=async()=>{attempts++;throw new TypeError('fixture connection lost');};
  await assert.rejects(request('/backend/create-ctf.php',{method:'POST',body:{name:'fixture'}}));
  assert.equal(attempts,1);
});
test('HTTP-success failure envelopes remain errors rather than successful UI actions',async()=>{
  globalThis.fetch=async()=>Response.json({success:false,message:'Fixture rejected'});
  await assert.rejects(request('/backend/profile.php'),(error:unknown)=>error instanceof ApiError&&error.message==='Fixture rejected');
});
test('API calls cannot target infrastructure services or external origins',async()=>{
  await assert.rejects(request('https://external.invalid/backend/api'));
  await assert.rejects(request('/launch-challenge'));
});
