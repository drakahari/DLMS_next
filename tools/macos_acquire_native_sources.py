#!/usr/bin/env python3
"""Read installed producer evidence; optionally download pinned source archives only."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from package_macos.native_materials import prepare, prepare_wheel_native

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download', action='store_true', help='HTTPS source archives only; SHA-256 checked against installed formula; no install or execution')
    parser.add_argument('--wheel-native', action='store_true', help='standalone Qt-wheel FFmpeg7.1.5 source and native producer facts; official HTTPS first-acquisition digest, no signature claim')
    arguments = parser.parse_args()
    path = (prepare_wheel_native if arguments.wheel_native else prepare)(download=arguments.download)
    report = json.loads(path.read_text())
    print(json.dumps({'index': str(path), 'producers': len(report.get('producers', report.get('sources', []))),
                      'complete': report['complete'], 'unresolved': report['unresolved']}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
