#!/usr/bin/env python3
"""Read-only MCP protocol discovery; prints schemas, never poem bodies or session identifiers."""
import json
import urllib.request
import sys

endpoint = 'https://poemship.com/mcp'
headers = {'Content-Type':'application/json','Accept':'application/json, text/event-stream','User-Agent':'CoDoc/1.0 (https://codoc.site)'}
def call(message):
    req=urllib.request.Request(endpoint,data=json.dumps(message).encode(),headers=headers)
    with urllib.request.urlopen(req,timeout=20) as response:
        session=response.headers.get('Mcp-Session-Id')
        if session: headers['Mcp-Session-Id']=session
        raw=response.read(1000001).decode()
    if not raw.strip():return {}
    if raw.lstrip().startswith('{'):return json.loads(raw)
    for block in raw.split('\n\n'):
        data='\n'.join(line[5:].strip() for line in block.splitlines() if line.startswith('data:'))
        if data:
            value=json.loads(data)
            if value.get('id')==message.get('id'):return value
    raise RuntimeError('No matching MCP response')
init=call({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'codoc-source-audit','version':'1.0'}}})
headers['MCP-Protocol-Version']=init.get('result',{}).get('protocolVersion','2025-03-26')
call({'jsonrpc':'2.0','method':'notifications/initialized'})
result=call({'jsonrpc':'2.0','id':2,'method':'tools/list'})
for tool in result.get('result',{}).get('tools',[]):
    if '--sample' not in sys.argv: print(json.dumps({'name':tool['name'],'description':tool.get('description'),'inputSchema':tool.get('inputSchema')},ensure_ascii=True))
if '--sample' in sys.argv:
    for index,(name,args) in enumerate([('library_guide',{'language':'ru'}),('find_poems',{'language':'ru','audience':'children','need':'smile','max_lines':24,'limit':1})],3):
        response=call({'jsonrpc':'2.0','id':index,'method':'tools/call','params':{'name':name,'arguments':args}}).get('result',{})
        print(name,'result fields',list(response.keys()))
        structured=response.get('structuredContent')
        if structured is None:
            for item in response.get('content',[]):
                if item.get('type')=='text':
                    try:structured=json.loads(item['text']);break
                    except ValueError:print('text-format prefix',item['text'][:100])
        def describe(value,depth=0):
            if isinstance(value,dict):return {key:('TEXT OMITTED' if any(word in key.lower() for word in ['text','opening','excerpt','lines','summary','description']) else describe(item,depth+1)) for key,item in value.items()}
            if isinstance(value,list):return [describe(item,depth+1) for item in value[:3]]
            return value
        if structured is not None:print(json.dumps(describe(structured),ensure_ascii=True)[:5000])
