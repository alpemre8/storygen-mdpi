# Rewrite V1.3

Rewrite-only block with two active paper contracts:

- `DP-v1`: direction-only baseline
- `CG-v1`: the same source/preservation/output contract plus numerical current, target and delta values

Reference screenplay and reference scene identities are forbidden in both active prompt conditions. Historical metadata-on CG remains `CG-v0-meta` and is not active.

V1.3 hardening:

- exact user/system/repair/method-config hashes and a prompt-bundle hash are stored in every run manifest
- information-policy hash is stored in every run manifest
- server model SHA, alias, quantization, slots, context and continuous batching are checked before generation
- rendered prompt requests are checked for metadata leakage and DP/CG information parity
- `cli/import_legacy_dp_run.py` strictly imports old DP outputs only when every per-scene request artifact proves the DP-v1 contract and exact scene order

## Run-directory contract

Canonical output root is the explicitly supplied external `<runs-root>/02-rewrite/`. Rewrite run directories are direct children of that root and canonical run IDs must encode `rwv1_3`. Do not create `<runs-root>/02-rewrite/rewrite-v1.3/` or another version-only wrapper for new runs. Semantic categories such as `benchmarks/` and `server_sessions/` remain allowed. This does not change the DP-v1/CG-v1 scientific or prompt contract.


## Direction policy (V1.3.1)

The rewrite directive uses the sign of the target delta directly: positive = increase, negative = decrease, and exact zero = maintain. There is no direction threshold or deadband. CG-v1 still receives the numerical current/target/delta values; DP-v1 receives only the categorical natural-language direction.

All run commands must pass an explicit external `--output-root`; the CLI has no in-repository default.
