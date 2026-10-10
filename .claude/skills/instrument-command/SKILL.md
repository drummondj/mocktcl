---
name: instrument-command
description: Teach the coverage instrumenter about a Tcl command that takes script bodies (e.g. a new control structure or a project DSL), so code inside those bodies gets line/branch coverage.
---

# Adding a script-taking command to the instrumenter

Coverage only reaches code inside braced arguments that `src/mocktcl/instrument.py`
knows are scripts. Everything else is treated as data and left alone. This is
deliberate: instrumenting data would corrupt it.

1. Find the command's syntax and decide which word indexes are scripts.
   Word 0 is the command name.
2. Simple cases go in the `SCRIPT_ARGS` table:
   - fixed index: `"while": (2,)`
   - last word: use `-1`
   - index depends on the word count: write a small resolver function, like the
     existing ones for `catch`, `dict` and `uplevel`, and register it in `SCRIPT_RESOLVERS`.
3. If the body is itself a *definition script* whose commands take bodies
   (e.g. a TclOO class body), mark it with the context name, so that nested commands
   are looked up in that context's table (see `OO_DEFINE_ARGS`).
4. Branch semantics (arms) are only for real conditionals. Follow the `if` and
   `switch` handlers, and remember:
   - The probe goes at the very start of the arm body: `::mocktcl::_b <id>; `
   - An implicit arm, when you add one, must return "" and must not change semantics.
5. Add tests in `tests/test_instrument.py`:
   - The instrumented text has exactly the same number of lines as the original.
   - Running it under `tclsh` gives the same result as the original.
   - The manifest has the expected executable lines and branch arms.
6. Run the `dev-test` skill.
