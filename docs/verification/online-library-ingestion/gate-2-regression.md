# Gate 2 regression evidence

**Resolution addendum:** Gate 2A fixed the shared collection-cache invalidation/retry owner. The exact failed test passed and the complete desktop suite passed 48/48 in 56.0 seconds. The initial failure analysis below is retained as evidence, not as the current gate outcome. See [gate-2a-verification.md](gate-2a-verification.md).

## Isolation proof

Every runtime test printed and verified all of these conditions before test execution:

- `CP_TEST_MODE=1`;
- a new GUID-named `CP_TEST_ROOT` below `C:\Users\dante\AppData\Local\Temp`;
- the catalog path and fixture media were inside that isolated root;
- configured live roots, including `E:\Movies`, did not overlap the test root;
- no test opened the production catalog or scanned a configured live media root.

The live CP and qBittorrent processes were not restarted. At the final check, CP remained PID 8336 on port 5000 and qBittorrent remained its child PID 42792 on port 8686. Ports 5117 and 5119 had no listener.

## Backend and contract tests

Final Python discovery:

```text
Ran 1025 tests in 159.495s
OK
```

Gate 0 was 1002 tests. Gate 2 adds 23 deterministic tests covering the writer lease and transaction boundary, exact-path and bounded-directory reconciliation, outside-root rejection, targeted/full parity, ownership, status redaction, queue bounds and serialization, stability thresholds, and zero-filesystem Movie View reads.

Other recorded runs during diagnosis:

- existing Library reconciliation selection after correcting the review condition: 26 passed;
- existing targeted reconciliation and catalog coverage: 91 passed in 57.287s;
- focused maintenance/catalog coverage after removing Movie View restats: 49 passed in 47.362s;
- order-sensitive coordinator construction proof: 34 passed;
- pre-final full discovery: 1023 passed in 125.066s;
- final full discovery after all changes: 1025 passed in 159.495s.

The final run retained two pre-existing warnings from Gate 0: an unclosed temporary file in the catalog-store path and an unclosed `dist/index.html` reader in a route test.

Two deterministic extraction defects were found and corrected before the final run:

1. The extracted review path initially omitted the existing `(not record and newly_added)` condition. The current expression restores the old behavior exactly.
2. A process-wide coordinator initially captured patched functions from an earlier unittest. Dependency callbacks now resolve dynamically, so test order and runtime patching cannot freeze a temporary dependency into the authoritative owner.

Neither failure was treated as flaky or rerun without diagnosis.

## Node, packaged runtime, and build

- Node: all 13 explicit `.test.mjs` files passed, 75/75 tests, 217.5375 ms.
- Packaged/native-player focused coverage: all 97 tests are included in the final Python discovery and passed.
- Vite production build: 1,651 modules, 35 files, 1,795,902 bytes, 2.32 s. Output used a unique temporary directory; repository `dist` was not overwritten.
- Gate 0 build parity: the module count, file count, and output bytes are identical.

## Playwright: gate-blocking failure

Result:

```text
47 passed
1 failed
```

Failed test:

```text
tests/e2e/app-smoke.spec.js:1233
Library collection never shows a false zero and opens full collection from the hero entry
expected: 3 movies • 1 owned
received: SQL CollectionLoading collection...
```

The retained Playwright trace establishes this sequence:

1. The test opens an expanded Library card and begins `/api/library/collection/7001`.
2. Leaving Library aborts that request with `net::ERR_ABORTED`.
3. Returning to Library preserves the expanded-card state but issues no replacement collection request.
4. The expanded card therefore remains at `Loading collection...`.

The test mocks the collection APIs, so the Gate 2 backend reconciliation and SQL changes do not produce this behavior. The current frontend cache owner, `src/hooks/useMovieCollectionCache.js`, aborts the pending request on route departure and does not recover it when the persisted expanded state is restored. Gate 0 passed this suite once, but the trace now proves a genuine pre-existing route/cache race rather than a Gate 2 backend failure.

The suite was not rerun until green. Under the zero-regression contract, a diagnosed pre-existing failure still blocks Gate 2 acceptance.

### Launcher incident and cleanup

The repository PowerShell launcher first failed before test execution because `Start-Process` received duplicate case-insensitive `Path`/`PATH` environment entries. A wrapper attempt started one isolated Python test process, PID 4160, on port 5117 and failed its cleanup step. Its command line, start time, and listener were verified before stopping that exact isolated PID. Live CP and qBittorrent were untouched.

The actual suite then ran through equivalent `.NET ProcessStartInfo` startup with a unique test root. Its isolated backend was PID 31928 on port 5117 and was stopped after the suite. No isolated listener remained.

## Regression conclusion

Backend, Node, packaging, build, ownership, isolation, and performance proof pass. Desktop Playwright initially failed 47/48; after the narrow Gate 2A owner correction, it passed 48/48. Gate 2 therefore passes.
