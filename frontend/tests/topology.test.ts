import assert from 'node:assert/strict';
import {test} from 'node:test';
import {topology} from '../src/lib/topology.ts';
test('topology preserves multi-network machines and filters stale or duplicated connections', () => {
  const graph=topology([{key:'one',name:'Target'},{key:'two',name:'Other'}],[
    {key:'entry',name:'Entry',accessible:true,dmz:false,machines:['one','one','missing']},
    {key:'dmz',name:'DMZ',accessible:false,dmz:true,machines:['one','two']},
  ]);
  assert.deepEqual(graph.edges.map(e=>[e.network,e.machine]),[['entry','one'],['dmz','one'],['dmz','two']]);
  assert.equal(graph.networks[1].dmz,true);
  for(const node of [...graph.networks,...graph.machines]) assert.ok(node.y>0 && node.y<graph.height);
  assert.equal(graph.machines.length,2);
});
test('empty and maximum-size previews have finite bounds and unique machine positions',()=>{
  assert.equal(topology([],[]).edges.length,0);
  const machines=Array.from({length:20},(_,i)=>({key:String(i),name:'Machine '+i}));
  const graph=topology(machines,[]);
  assert.equal(new Set(graph.machines.map(vm=>vm.y)).size,20);
  assert.ok(Number.isFinite(graph.height));
});
