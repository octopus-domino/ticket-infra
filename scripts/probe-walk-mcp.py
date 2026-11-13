#!/usr/bin/env python3
"""Read-only HTTP MCP discovery: names/schemas only; no response payloads or sessions logged."""
import json
import urllib.request
import urllib.error
headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
endpoint='https://gateway.pipeworx.io/commons-wikimedia/mcp'
def call(message):
    request=urllib.request.Request(endpoint,data=json.dumps(message).encode(),headers=headers)
    with urllib.request.urlopen(request,timeout=15) as response:
        if response.headers.get('Mcp-Session-Id'):headers['Mcp-Session-Id']=response.headers['Mcp-Session-Id']
        raw=response.read(1000001).decode()
    if not raw.strip():return {}
    if raw.lstrip().startswith('{'):return json.loads(raw)
    for line in raw.splitlines():
        if line.startswith('data:'):
            value=json.loads(line[5:])
            if value.get('id')==message.get('id'):return value
    return {}
try:
    result=call({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'codoc-walk-audit','version':'1.0'}}})
    headers['MCP-Protocol-Version']=result.get('result',{}).get('protocolVersion','2025-03-26')
    call({'jsonrpc':'2.0','method':'notifications/initialized'})
    result=call({'jsonrpc':'2.0','id':2,'method':'tools/list'})
    print(json.dumps([{'name':tool['name'],'inputSchema':tool.get('inputSchema')} for tool in result.get('result',{}).get('tools',[]) if tool['name'] in ['commons_wikimedia_search','file_info']],ensure_ascii=True))
    result=call({'jsonrpc':'2.0','id':3,'method':'tools/call','params':{'name':'commons_wikimedia_search','arguments':{'query':'Eiffel Tower','limit':1}}}).get('result',{})
    print('searchResultFields',list(result.keys()),'isError',result.get('isError'))
    search=None
    for content in result.get('content',[]):
        if content.get('type')=='text':
            try:
                value=json.loads(content['text'])
                if isinstance(value,dict) and value.get('query',{}).get('search'):search=value['query']['search'][0]['title']
                print('searchDataFields',list(value.keys()) if isinstance(value,dict) else type(value).__name__)
                if isinstance(value,dict):
                    for key,item in value.items():
                        print(key,'type',type(item).__name__,'keys',list(item.keys())[:12] if isinstance(item,dict) else list(item[0].keys())[:12] if isinstance(item,list) and item and isinstance(item[0],dict) else '')
            except ValueError: print('Non-JSON response')
    if search:
        result=call({'jsonrpc':'2.0','id':4,'method':'tools/call','params':{'name':'file_info','arguments':{'title':search}}}).get('result',{})
        for content in result.get('content',[]):
            if content.get('type')=='text':
                value=json.loads(content['text'])
                print('fileInfoFields',list(value.keys()))
                pages=value.get('query',{}).get('pages',{})
                for page in pages.values() if isinstance(pages,dict) else pages:
                    print('fileInfoPageKeys',list(page.keys()))
                    for info in page.get('imageinfo',[]):print('imageInfoKeys',list(info.keys()),'licenseKeys',list(info.get('extmetadata',{}).keys()))
except urllib.error.HTTPError as error:
    print('MCP HTTP status:',error.code)
except Exception as error:
    print('MCP unavailable:',type(error).__name__)
