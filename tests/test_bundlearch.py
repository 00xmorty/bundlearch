import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TOOL = Path(__file__).resolve().parents[1] / 'bundlearch'
loader = importlib.machinery.SourceFileLoader('bundlearch', str(TOOL))
spec = importlib.util.spec_from_loader(loader.name, loader)
ba = importlib.util.module_from_spec(spec)
loader.exec_module(ba)
ARM, INTEL = 0x0100000c, 0x01000007


def thin(cpu, endian='<', bits=64):
    return struct.pack(endian + ('IIIIIIII' if bits == 64 else 'IIIIIII'),
                       *([0xfeedfacf if bits == 64 else 0xfeedface, cpu, 0, 2, 0, 0, 0] +
                         ([0] if bits == 64 else [])))


def fat(cpus, width=20, endian='>'):
    end = 8 + len(cpus) * width
    result = struct.pack(endian + 'II', 0xcafebabe if width == 20 else 0xcafebabf, len(cpus))
    for i, cpu in enumerate(cpus):
        row = [cpu, 0, end + i * 32, 32, 0] + ([0] if width == 32 else [])
        result += struct.pack(endian + ('IIIII' if width == 20 else 'IIQQII'), *row)
    return result + b''.join(thin(cpu) for cpu in cpus)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'Demo App.app'
        (self.root / 'Contents' / 'Helpers').mkdir(parents=True)

    def file(self, name, data):
        path = self.root / 'Contents' / 'Helpers' / name
        path.write_bytes(data)
        return path

    def scan(self, **kw):
        return ba.scan(str(self.root), 'arm64', kw.get('max_entries', 50000))

    def test_thin_endian_and_32_64(self):
        for endian in ('<', '>'):
            for bits, cpu in ((32, 12), (64, ARM)):
                with self.subTest(endian=endian, bits=bits):
                    p = self.file('main', thin(cpu, endian, bits))
                    with p.open('rb') as stream:
                        self.assertEqual(ba.architectures(stream.fileno(), p.stat().st_size),
                                         ['arm' if bits == 32 else 'arm64'])

    def test_helper_mismatch(self):
        self.file('main', thin(ARM))
        self.file('intel helper', thin(INTEL))
        result = self.scan()
        self.assertEqual(result['status'], 'MISSING')
        self.assertEqual(sum(r['missing_required'] for r in result['macho_files']), 1)

    def test_fat_variants(self):
        for width in (20, 32):
            for endian in ('<', '>'):
                self.file('universal', fat([ARM, INTEL], width, endian))
                self.assertEqual(self.scan()['status'], 'PRESENT')
                self.assertEqual(self.scan()['macho_files'][0]['architectures'], ['arm64', 'x86_64'])

    def test_truncated_macho_unknown(self):
        self.file('bad', thin(ARM)[:8])
        self.assertEqual(self.scan()['status'], 'UNKNOWN')
        self.assertEqual(self.scan()['issues'][0]['code'], 'truncated_header')

    def test_bad_fat_bounds(self):
        data = bytearray(fat([ARM]))
        data[16:20] = struct.pack('>I', 10000)
        self.file('bad', data)
        self.assertEqual(self.scan()['issues'][0]['code'], 'invalid_slice_bounds')

    def test_cpu_mismatch(self):
        data = bytearray(fat([ARM]))
        data[8:12] = struct.pack('>I', INTEL)
        self.file('bad', data)
        self.assertEqual(self.scan()['issues'][0]['code'], 'slice_cpu_mismatch')

    def test_overlap(self):
        data = bytearray(fat([ARM, INTEL]))
        data[36:40] = data[16:20]
        self.file('bad', data)
        self.assertEqual(self.scan()['issues'][0]['code'], 'overlapping_slices')

    def test_empty_and_text_unknown(self):
        self.file('note', b'not a binary')
        self.assertEqual(self.scan()['status'], 'UNKNOWN')
        self.assertEqual(self.scan()['ignored_non_macho'], 1)

    def test_unknown_cpu_is_missing(self):
        self.file('future', thin(0x12345))
        self.assertEqual(self.scan()['status'], 'MISSING')
        self.assertEqual(self.scan()['macho_files'][0]['architectures'], ['cpu_00012345'])

    def test_outside_and_directory_symlinks_not_followed(self):
        outside = Path(self.tmp.name) / 'secret'
        outside.write_bytes(thin(INTEL))
        os.symlink(outside, self.root / 'outside')
        os.symlink(self.root, self.root / 'loop')
        self.file('main', thin(ARM))
        result = self.scan()
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertEqual(len(result['macho_files']), 1)
        self.assertNotIn(str(outside), json.dumps(result))

    def test_fifo_never_opened(self):
        os.mkfifo(self.root / 'pipe')
        self.assertEqual(self.scan()['issues'][0]['code'], 'special_file_skipped')

    def test_unreadable_is_unknown(self):
        self.file('main', thin(ARM))
        original = os.open
        def guarded(name, *args, **kwargs):
            if name == 'main':
                raise PermissionError('private input path')
            return original(name, *args, **kwargs)
        with mock.patch.object(ba.os, 'open', side_effect=guarded):
            result = self.scan()
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertNotIn('private input path', json.dumps(result))

    def test_entry_limit(self):
        self.file('main', thin(ARM))
        self.assertEqual(self.scan(max_entries=1)['issues'][-1]['code'], 'entry_limit')

    def test_missing_root_no_path_leak(self):
        result = ba.scan(str(self.root / 'private'), 'arm64', 100)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_cli_json_exit_codes_and_no_mutation(self):
        p = self.file('space newline\nhelper', thin(INTEL))
        before = p.read_bytes()
        run = subprocess.run([sys.executable, str(TOOL), str(self.root), '--require', 'arm64', '--json'],
                             text=True, capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 1)
        self.assertEqual(json.loads(run.stdout)['status'], 'MISSING')
        self.assertEqual(p.read_bytes(), before)
        self.assertNotIn(str(self.root), run.stdout)

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS Mach-O check')
    def test_real_native_binary_against_lipo(self):
        import shutil
        binary = self.root / 'Contents' / 'Helpers' / 'native helper'
        shutil.copyfile('/usr/bin/true', binary)
        native = subprocess.check_output(['/usr/bin/lipo', '-archs', str(binary)], text=True).split()
        # lipo reports subtypes (arm64e/x86_64h); scanner intentionally reports CPU families.
        families = sorted({'arm64' if a.startswith('arm64') else
                           'x86_64' if a.startswith('x86_64') else a for a in native})
        family = 'arm64' if 'arm64' in families else 'x86_64'
        run = subprocess.run([sys.executable, str(TOOL), str(self.root), '--require', family, '--json'],
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0)
        self.assertEqual(json.loads(run.stdout)['macho_files'][0]['architectures'], families)
        print('Native CLI/lipo CPU-family agreement:', ','.join(families), '(native:', ','.join(native) + ')')

    def test_java_magic_is_conservative_unknown(self):
        self.file('Example.class', b'\xca\xfe\xba\xbe\x00\x00\x00\x41')
        self.assertEqual(self.scan()['status'], 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
