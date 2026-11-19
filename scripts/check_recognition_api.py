#!/usr/bin/env python3
"""Recognize one explicitly supplied PDF/image and save the private result outside the repository."""
import argparse
import base64
import json
from pathlib import Path
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True)
    parser.add_argument('--file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--page', type=int, default=1)
    args = parser.parse_args()
    content = args.file.read_bytes()
    if not content or len(content) > 8 * 1024 * 1024 or not 1 <= args.page <= 500:
        parser.error('Use a nonempty document up to 8 MiB and page 1..500')
    encoded = base64.b64encode(content).decode()
    pdf = args.file.suffix.lower() == '.pdf'
    path = '/api/guest/recognition/pdf-page' if pdf else '/api/guest/recognition'
    body = dict(pdf=encoded, page=args.page, editable=True) if pdf else dict(image=encoded, language='rus+eng', engine='ocr')
    call = urllib.request.Request(args.base_url.rstrip('/') + path, data=json.dumps(body).encode(),
                                  headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(call, timeout=120) as response:
        result = json.load(response)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    draft = result.get('draft') or result
    elements = draft.get('elements', [])
    print(json.dumps(dict(pages=result.get('pages', 1), elements=len(elements),
                         tables=sum(item.get('type') == 'table' for item in elements))))


if __name__ == '__main__':
    main()
