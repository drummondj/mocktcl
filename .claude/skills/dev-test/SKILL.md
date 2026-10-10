---
name: dev-test
description: Run mocktcl's own test suite and the example Tcl projects to verify a change. Use after editing anything under src/mocktcl/.
---

# Verifying a mocktcl change

1. Make sure the venv exists. If it doesn't, create it:
   `python3 -m venv .venv && .venv/bin/pip install -q -e . pytest`
2. Unit and end-to-end tests: `.venv/bin/pytest -q`
   - To narrow down: `.venv/bin/pytest -q tests/test_instrument.py -k switch`
3. Dogfood on the example project:
   `cd examples/calculator && ../../.venv/bin/mocktcl -v --cov-report text --cov-report html:/tmp/mocktcl-html`
   - The suite should pass, except for tests that are named as failing on purpose.
   - Check that the coverage numbers are believable. A line that obviously runs must not show as missed.
4. If you changed instrumentation, also make sure instrumented code still behaves identically:
   `.venv/bin/python -m mocktcl.instrument path/to/file.tcl` prints the instrumented source. Diff its line count against the original (it must be equal).
5. If you changed `harness.tcl`, run one test file with the harness directly to see raw events. `mocktcl --keep-tmp` prints where the job and results files are kept.

Report failures with the actual output. Don't paraphrase it.
