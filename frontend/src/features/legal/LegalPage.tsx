import { createElement, type ReactNode } from 'react';
import documents from './documents.json';
type Node = string | {tag: string; attrs: {id?: string; href?: string}; children: Node[]};
function render(node: Node, key: number): ReactNode {
  if (typeof node === 'string') return node;
  const attrs = node.tag === 'a' ? {...node.attrs, target: '_blank', rel: 'noopener noreferrer'} : node.attrs;
  if (node.tag === 'br') return createElement('br',{key});
  return createElement(node.tag,{...attrs,key},node.children.map(render));
}
export function LegalPage({kind}: {kind: 'impressum' | 'privacy-policy'}) {
  return <article className="legal-page card" lang="de">{(documents[kind] as Node[]).map(render)}</article>;
}
