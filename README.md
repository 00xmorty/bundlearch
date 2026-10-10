# BundleArch

Find a wrong-architecture helper hiding inside an otherwise correctly packaged macOS app. An offline, read-only Mach-O header inventory for every regular file under an explicitly chosen directory — not just the main executable.

Python 3.9+ standard library only. Runs on macOS and Linux; Linux can inspect unpacked macOS bundles. No `lipo`, compiler, network, or package installation is needed to run the scanner.

## Run

```sh
git clone https://github.com/00xmorty/bundlearch.git
cd bundlearch
python3 bundlearch '/path/to/Example App.app' --require arm64
python3 bundlearch '/path/to/Example App.app' --require x86_64 --json
```

Or download the single `bundlearch` script from the GitHub release, review it, then run `python3 bundlearch ...`. There is no system-wide installer.

Example output from a synthetic fixture (not a real user's app):

```text
BundleArch 0.1.0: MISSING (header inventory, not runtime compatibility)
MISSING "Contents/Helpers/intel helper" x86_64
PRESENT "Contents/Helpers/main" arm64
Mach-O files: 2; entries: 4; issues: 0
```

## Exit codes

- `0`: PRESENT — at least one Mach-O header found, every inspected header has the requested CPU family, no scan issues.
- `1`: MISSING — at least one inspected Mach-O lacks the requested family, no scan issues.
- `2`: UNKNOWN — unreadable/malformed inputs, skipped symlink/special file, scan limit, or no Mach-O found. Partial mismatches remain in the output; UNKNOWN takes precedence.

Required family choices: `arm64`, `x86_64`, `arm`, `i386`. Unknown CPU values remain visible as numeric labels. JSON schema version 1 includes status, entries, issues and individual relative-path architecture results.

## Safety

- Never executes binaries, loads plugins, launches apps, installs Rosetta, modifies signatures, or repairs anything. No sudo, telemetry or network.
- Only bounded headers are read from regular files. Thin and 32/64-bit universal headers are checked, including slice bounds, alignment, overlaps and CPU agreement.
- Symlinks (including the root itself) are not followed. Directory-descriptor-relative access and no-follow/nonblocking opens avoid opening a substituted leaf symlink or FIFO. Symlinks and special files produce UNKNOWN, even when they are normal framework aliases.
- Root ancestors must be trusted; do not scan hostile, concurrently modified trees. File-change checks are best effort, not a security sandbox.
- Absolute input paths and raw exception details are suppressed. Relative filenames may still be private: review all output before sharing. Control characters are escaped in text and JSON.

## Limitations

This is a CPU-family **header inventory**, not proof that an app works, is signed, is safe, or supports a deployment target. It does not validate load commands, signatures, dyld dependency resolution, CPU subtypes (e.g. arm64e), platform variants, or runtime behavior. An optional Intel-only helper may be intentional; a missing slice is a review finding, not a verdict that the app is broken.

Does not open DMGs, ZIPs, archives, or static-library members; unpack an app yourself first. A directory with only scripts/data gives UNKNOWN, not a compatibility pass. Java `.class` shares a universal-header magic value and may conservatively produce UNKNOWN. Headers with more than 64 slices are unsupported. Default limit is 50,000 visited entries (`--max-entries 1..1000000`), with 64 directory levels. Directory enumeration itself is not memory-bounded, and slow mounts cannot be given a reliable wall-clock timeout. Use a local, stable bundle and a caller-imposed timeout when needed.

## Verify

```sh
python3 -m unittest discover -s tests -v
python3 bundlearch --version
```

CI runs the same tests on macOS and Linux. Tests use original synthetic headers, spaces/newlines in names, universal variants, malformed slices, no-follow links, FIFO, permission failures and CLI exit codes.

Format references (documentation only; no upstream implementation copied): Apple's `cctools` `include/mach-o/loader.h` and `include/mach-o/fat.h`. Original scanner implementation, MIT licensed.
