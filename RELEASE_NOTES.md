# v0.1.0

- Original dependency-free Mach-O CPU-family inventory, including embedded helpers and dylibs.
- Thin little/big-endian headers and universal 32/64-bit slice tables.
- Explicit PRESENT/MISSING/UNKNOWN exit semantics and JSON schema v1.
- Read-only descriptor-relative traversal: no symlink following, no special-file opens, no binary execution.
- Conservative malformed-header checks, entry/depth limits and escaped relative paths.
- Synthetic unit tests and macOS/Linux CI.

Not a runtime, signature, CPU-subtype or dependency compatibility validator. Normal symlink-containing frameworks produce UNKNOWN. Review relative filenames before sharing. No telemetry or automatic repairs.
