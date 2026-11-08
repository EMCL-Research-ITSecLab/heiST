#!/usr/bin/env python3
"""Import downloaded operator legal-page main content without scripts/navigation.

Download verified HTTPS snapshots to a private directory first. Review the Git
changes and policy revision before deployment. No network requests are made here.
"""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit
import argparse,hashlib,json
from datetime import datetime,timezone
allowed={'h1','h2','h3','p','ul','ol','li','a','strong','em','b','i','br','div','span','section','address'}
class Content(HTMLParser):
 def __init__(self):super().__init__(convert_charrefs=True);self.active=False;self.nodes=[];self.stack=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag=='main':self.active=True;return
  if not self.active:return
  if tag in ('script','style','iframe'):self.skip+=1;return
  if self.skip:return
  if tag not in allowed:raise ValueError('Review unsupported legal content tag: '+tag)
  attr=dict(attrs);safe={}
  if attr.get('id'):safe['id']=attr['id']
  if tag=='a':
   href=urljoin('https://emcl-ctf.iwr.uni-heidelberg.de/',attr.get('href',''))
   if urlsplit(href).scheme not in ('https','mailto','tel'):raise ValueError('Review legal link')
   if href.endswith('/assets/fontawesome/LICENSE.txt'):href='/assets/ui/fontawesome-license.txt'
   safe['href']=href
  node={'tag':tag,'attrs':safe,'children':[]}
  (self.stack[-1]['children'] if self.stack else self.nodes).append(node)
  if tag!='br':self.stack.append(node)
 def handle_endtag(self,tag):
  if tag=='main':self.active=False;return
  if not self.active:return
  if tag in ('script','style','iframe'):self.skip-=1;return
  if self.skip:return
  if tag!='br':
   if not self.stack or self.stack[-1]['tag']!=tag:raise ValueError('Review unmatched markup')
   self.stack.pop()
 def handle_data(self,data):
  if self.active and not self.skip and data:
   (self.stack[-1]['children'] if self.stack else self.nodes).append(data)
def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-directory',required=True,type=Path)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[2];docs={};sources={}
    for name in ('impressum','privacy-policy','terms-of-service'):
     body=(args.source_directory/(name+'.html')).read_bytes();p=Content();p.feed(body.decode())
     if p.stack:raise ValueError('Incomplete legal content')
     docs[name]=p.nodes;sources[name]={'url':'https://emcl-ctf.iwr.uni-heidelberg.de/'+name,'response_sha256':hashlib.sha256(body).hexdigest()}
    version=hashlib.sha256(json.dumps({name:docs[name] for name in ('privacy-policy','terms-of-service')},ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    folder=root/'frontend/src/features/legal';folder.mkdir(exist_ok=True)
    (folder/'documents.json').write_text(json.dumps(docs,ensure_ascii=False,indent=2)+'\n')
    (root/'assets/legal-sources.json').write_text(json.dumps({'version':version,'sources':sources,'imported_at':datetime.now(timezone.utc).date().isoformat(),'scope':'main legal content only; scripts and site navigation excluded'},indent=2)+'\n')
    (root/'heist/legal.py').write_text('''"""Bundled operator legal pages; bump the revision when their contents change."""\nIMPRINT_URL = "https://emcl-ctf.iwr.uni-heidelberg.de/impressum"\nPRIVACY_URL = "https://emcl-ctf.iwr.uni-heidelberg.de/privacy-policy"\nTERMS_URL = "https://emcl-ctf.iwr.uni-heidelberg.de/terms-of-service"\nLEGAL_VERSION = "'''+version+'"\n')
    print(json.dumps({'pages':list(docs),'version':version,'source_bytes':sum((args.source_directory/(n+'.html')).stat().st_size for n in docs)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
