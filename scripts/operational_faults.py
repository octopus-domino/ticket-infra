#!/usr/bin/env python3
"""Exercise provider, OCR, SMTP and job failures on disposable CoDoc services."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import time

from operational_lab import CLIENT, Lab, application, wait_ready


def post(lab, service, port, path, headers, payload, timeout=15):
    return lab.request(service, port, path, headers, json.dumps(payload).encode(), timeout=timeout)


def run(lab, args):
    upstream = lab.root / 'OperationalUpstream.class'
    shutil.copyfile(args.upstream_class, upstream)
    document = application(lab, 'document', args.document_jar, None, travel=False)
    routing = application(lab, 'routing', args.routing_jar, None, travel=False)
    document['environment'].update(
        SMTP_HOST='upstream', SMTP_PORT='2525', SMTP_SSL='false', SMTP_AUTH='false',
        SMTP_READ_TIMEOUT='1800', APP_RECOGNITION_TESSERACT='/lab/missing-ocr-binary',
    )
    routing['environment'].update(BROUTER_HTTP_ENABLED='true', BROUTER_HTTP_URL='http://upstream:8080')
    lab.define({
        'client': CLIENT,
        'document': document,
        'routing': routing,
        'upstream': CLIENT | {
            'mem_limit': '96m', 'entrypoint': ['java', '-Xmx32m', '-cp', '/lab', 'OperationalUpstream'],
            'volumes': ['./OperationalUpstream.class:/lab/OperationalUpstream.class:ro'],
        },
    })
    try:
        lab.start('client', 'upstream', 'document')
        wait_ready(lab, 'document', 9080)
        headers = {'Content-Type': 'application/json'}
        status, body, _ = post(lab, 'document', 8080, '/api/auth/register', headers, {
            'email': 'faults@example.test', 'name': 'Fault drill', 'password': 'lab-only-password-123',
        })
        assert status == 201, status
        headers['Authorization'] = 'Bearer ' + json.loads(body)['accessToken']

        seed_image = (
            'iVBORw0KGgoAAAANSUhEUgAAAEYAAAAyCAIAAABu/zoEAAAATElEQVR4nO3PAQ0AAAjAIPuX1hy404DZ'
            'd2bfqSSoJKgkqCSoJKgkqCSoJKgkqCSoJKgkqCSoJKgkqCSoJKgkqCSoJKgkqCSoJKi0gAPGUd1Vg+QpSwAAAABJRU5ErkJggg=='
        )
        status, body, elapsed = post(lab, 'document', 8080, '/api/guest/recognition', headers, {
            'image': 'data:image/png;base64,' + seed_image, 'language': 'eng', 'engine': 'ocr',
        })
        result = json.loads(body)
        assert status == 200 and 'recognition.empty_result' in result['warnings'], (status, result)
        assert lab.request('document', 9080, '/actuator/health/readiness', local=True)[0] == 200
        print(f'Missing OCR binary returned empty result HTTP {status} ({elapsed:.0f} ms), Document ready', flush=True)

        slide = {'id': 'fault', 'name': 'Fault drill', 'width': 595, 'height': 842,
                 'background': '#ffffff', 'elements': []}
        message = {'requestId': 'lab-mail-ambiguous-response', 'inlineSlides': [slide],
                   'items': [{'to': 'synthetic@example.test', 'inlineValues': {}}]}
        status, _, _ = post(lab, 'document', 8080, '/api/email/send', headers, message, timeout=.5)
        assert status == 0, status
        for _ in range(10):
            attempts = lab.compose('logs', '--no-color', 'upstream').count(b'SMTP connection received')
            if attempts:
                break
            time.sleep(.2)
        assert attempts == 1, attempts
        time.sleep(2)
        status, response, elapsed = post(lab, 'document', 8080, '/api/email/send', headers, message)
        result = json.loads(response)
        assert status == 202 and result['sent'] == 0 and result['failed'] == 1, (status, result)
        assert lab.compose('logs', '--no-color', 'upstream').count(b'SMTP connection received') == 1
        print(f'SMTP failed after client timeout; retry HTTP {status} ({elapsed:.0f} ms), one SMTP connection', flush=True)

        lab.start('routing')
        wait_ready(lab, 'routing', 9093)
        route = {'start': {'longitude': 13.40, 'latitude': 52.50},
                 'end': {'longitude': 13.42, 'latitude': 52.51}, 'mode': 'foot'}
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(post, lab, 'routing', 8093, '/api/routing/v1/road', headers, route, 20)
            for _ in range(10):
                if b'BRouter request received' in lab.compose('logs', '--no-color', 'upstream'):
                    break
                time.sleep(.2)
            else:
                raise RuntimeError('The road provider did not receive the synthetic request')
            assert lab.request('routing', 9093, '/actuator/health/readiness', local=True)[0] == 200
            assert lab.request('routing', 8093, '/api/walks/v1/places/themes')[0] == 200
            status, _, elapsed = pending.result()
        assert status == 503 and elapsed >= 10_000, (status, elapsed)
        print(f'Stalled BRouter HTTP {status} ({elapsed:.0f} ms), categories and readiness available', flush=True)

        job = {'inlineSlides': [slide] * 4, 'items': [{'inlineValues': {}}] * 120, 'format': 'pdf', 'packAs': 'zip'}
        status, body, _ = post(lab, 'document', 8080, '/api/generate', headers, job)
        assert status == 202, (status, body)
        path = '/api/generate/' + json.loads(body)['jobId']
        for _ in range(20):
            status, body, _ = lab.request('document', 8080, path, headers)
            if status == 200 and json.loads(body)['status'] == 'running':
                break
            time.sleep(.1)
        else:
            raise RuntimeError('The bounded lab job was never observed in flight')
        lab.verify()
        lab.compose('kill', '-s', 'SIGKILL', 'document')
        lab.compose('start', 'document')
        wait_ready(lab, 'document', 9080)
        status, body, _ = lab.request('document', 8080, path, headers)
        assert status == 200 and json.loads(body)['status'] == 'failed', (status, body)
        assert lab.request('document', 8080, path + '/result', headers)[0] == 409
        assert lab.request('document', 8080, path, {'Authorization': 'Bearer invalid'})[0] == 401
        print('Interrupted job reopened as failed after JVM restart, no partial result exposed', flush=True)
    finally:
        for service in ('document', 'routing', 'upstream'):
            if lab.compose('ps', '-aq', service).strip():
                (lab.root / f'{service}.log').write_bytes(lab.compose('logs', '--no-color', service))
        lab.close()
        for name in ('document', 'routing'):
            (lab.root / f'{name}.jar').unlink(missing_ok=True)


if __name__ == '__main__':
    if not __debug__:
        raise RuntimeError('Run acceptance drills with Python assertions enabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--document-jar', required=True, type=Path)
    parser.add_argument('--routing-jar', required=True, type=Path)
    parser.add_argument('--upstream-class', required=True, type=Path)
    args = parser.parse_args()
    run(Lab(), args)
