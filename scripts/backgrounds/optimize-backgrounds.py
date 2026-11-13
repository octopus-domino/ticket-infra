"""Lossless artwork optimization. Never resizes or quantizes; verifies decoded RGBA bytes.

Install Pillow, then run from the workspace root:
  python ticket-infra/scripts/backgrounds/optimize-backgrounds.py --source reports/background-originals
The local C:/sandpr/.cache/image-tools installation is also supported on this workstation.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor

infra = Path(__file__).resolve().parents[2]
project = infra.parent / 'ticket-editor'
local_tools = project.parent / '.cache/image-tools'
if local_tools.is_dir():
    sys.path.insert(0, str(local_tools))
from PIL import Image


def pixels(path):
    with Image.open(path) as image:
        image.load()
        return image.size, hashlib.sha256(image.convert('RGBA').tobytes()).hexdigest()


def optimize(source, destination):
    original_size = source.stat().st_size
    expected = pixels(source)
    target = destination / (source.stem + '.webp')
    png = source.with_suffix('.optimized.png')
    with Image.open(source) as image:
        image.load()
        kwargs = {key: image.info[key] for key in ['icc_profile', 'exif'] if image.info.get(key)}
        # In lossless mode quality controls encoder effort, not image quality.
        image.save(target, 'WEBP', lossless=True, exact=True, quality=85, method=4, **kwargs)
        png_kwargs = dict(kwargs)
        if 'dpi' in image.info:
            png_kwargs['dpi'] = image.info['dpi']
        image.save(png, 'PNG', optimize=True, compress_level=9, **png_kwargs)
    for output in [target, png]:
        if pixels(output) != expected:
            raise RuntimeError(f'Pixel mismatch: {output.name}')
    # Keep the PNG archive smaller too, replacing it only after byte-for-byte pixel validation.
    png_bytes = png.stat().st_size
    if png_bytes < original_size:
        os.replace(png, source)
    else:
        png.unlink()
    row = dict(id=source.stem, width=expected[0][0], height=expected[0][1],
               original_bytes=original_size, png_bytes=source.stat().st_size,
               webp_bytes=target.stat().st_size, rgba_sha256=expected[1], pixels_identical=True)
    # Full-resolution WebP is used by browsers; PNG remains available for print tooling.
    print(json.dumps({key: row[key] for key in ['id', 'original_bytes', 'webp_bytes', 'pixels_identical']}), flush=True)
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=project / 'public/backgrounds/lossless')
    parser.add_argument('--report', type=Path, default=infra / 'reports/background-optimization.json')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    sources = sorted(args.source.glob('*.png'))
    with ThreadPoolExecutor(max_workers=2) as workers:
        rows = list(workers.map(lambda source: optimize(source, args.output), sources))
    report = dict(count=len(rows), original_bytes=sum(row['original_bytes'] for row in rows),
                  lossless_webp_bytes=sum(row['webp_bytes'] for row in rows),
                  optimized_png_bytes=sum(row['png_bytes'] for row in rows), images=rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in report.items() if key != 'images'}), flush=True)
