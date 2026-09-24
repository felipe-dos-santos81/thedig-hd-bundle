# AGENTS.md

`thedig-textures` extracts every texture from GOG's *The Dig* `.app` into PNGs plus a
`manifest.json`, pixel-identical to ScummVM's decoder. Python 3.12, `pillow` runtime
dependency, `pytest` for tests, GPL-3.0-or-later.

## Commands

```
make install   # create .venv and install -e ".[dev]"
make check     # unit tests (game-marked tests deselected)
make oracle    # build the vendored C++ codec-37 reference oracle
make verify    # check + oracle + byte-exact SAN/NUT/LA1/AKOS differentials
```

Run `make check` after any code change; run `make verify` after touching a decoder,
the oracle, or a `tools/diff_*.py` script. The four differentials are the ground
truth: SAN 55/55, NUT 6/6, LA1 and AKOS byte-identical.

## Layout

- `digart/` — the decoders and writers: `san.py`, `codec37.py`, `bomp.py`, `nut.py`,
  `la1.py`, `akos.py`, `manifest.py`, `pngout.py`, `cli.py`, `errors.py`.
- `tools/` — the `diff_*.py` differential harnesses and `la1_census.py`.
- `vendor/san-oracle/` — verbatim upstream ScummVM sources (hash-pinned in
  `UPSTREAM.txt`) plus a thin `oracle_main.cpp` shim. Do not edit vendored files.
- `docs/la1-census.txt` — the normative LA1 inventory the decoders must match.
- `docs/superpowers/{specs,plans}/` — design spec and implementation plan.

## Invariants

- The game bundle at `~/Documents/The Dig®.app/Contents/Resources/game/game` is
  **read-only**. Never write under it; never commit extracted output (`out/` is
  gitignored).
- LA1 chunk sizes include the 8-byte header with no odd padding (`next = start +
  size`); SAN chunks pad to even. Do not "unify" the two strides.
- `has_alpha` and transparent-index normalization follow spec §5.1. Changing a
  decoder's transparency behavior changes the manifest contract.

## Tests

Consolidate tests. Prefer a few grouped test functions per module over one function
per case: related assertions (a decoder's variants, a module's error paths) belong in
the same function. Use `pytest.mark.parametrize` only when it genuinely clarifies;
it increases the reported test count, so grouping is usually better. Keep every
assertion when merging — consolidation must not reduce coverage.

- Aim for roughly ≤3 test functions per `tests/test_*.py` module, excluding
  `@pytest.mark.game` integration tests.
- Assert real decoded bytes/values, not mocks or call counts.
- Mark tests that need the real bundle with `@pytest.mark.game`; they are deselected
  by default and run via `pytest -m game`.
- Add synthetic fixtures under `tests/fixtures/`; do not embed real game data.
