#!/usr/bin/env python3
"""Run the installed server Tesseract on an explicitly supplied image, then remove uploaded inputs."""
import argparse
from pathlib import Path
import re
import shlex
import subprocess
import uuid
from runtime_publish import connection_arguments, ssh_options


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    connection_arguments(parser)
    parser.add_argument('--image', type=Path, required=True, help='PNG/JPEG image; rasterize PDF pages before this check')
    parser.add_argument('--output-dir', type=Path, required=True, help='Private local directory outside Git')
    parser.add_argument('--psm', type=int, nargs='+', default=[3, 11])
    parser.add_argument('--languages', default='rus+eng')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z_+]+', args.languages) or any(mode not in range(14) for mode in args.psm):
        parser.error('Invalid Tesseract languages or segmentation mode')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    options = ssh_options(args)
    remote = '/tmp/codoc-ocr-check-' + uuid.uuid4().hex + args.image.suffix.lower()

    def command(*parts, **kwargs):
        return subprocess.run(['ssh', *options, args.target, shlex.join(parts)], **kwargs)

    try:
        subprocess.run(['scp', *options, str(args.image.resolve(strict=True)), args.target + ':' + remote], check=True)
        command('docker', 'cp', remote, args.container + ':' + remote, check=True)
        for mode in args.psm:
            result = command('docker', 'exec', '-e', 'OMP_THREAD_LIMIT=1', args.container, 'tesseract',
                             remote, 'stdout', '-l', args.languages, '--oem', '1', '--psm', str(mode),
                             '--dpi', '300', '-c', 'preserve_interword_spaces=1', 'tsv', capture_output=True, check=True)
            (args.output_dir / ('psm-' + str(mode) + '.tsv')).write_bytes(result.stdout)
            print('Tesseract PSM ' + str(mode) + ': completed, TSV bytes=' + str(len(result.stdout)))
    finally:
        command('docker', 'exec', args.container, 'rm', '-f', remote, check=False)
        command('rm', '-f', remote, check=False)


if __name__ == '__main__':
    main()
