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
2. Register a resolver in the `SCRIPT_ARGS` table:
   - fixed index for a given word count: `"while": _fixed(3, 2)`
   - last word: use `-1`
   - index depends on the word count or subcommand: write a small resolver function,
     like the existing ones for `catch`, `dict` and `uplevel`.
3. If the body is itself a *definition script* whose commands take bodies
   (e.g. a TclOO class body), mark it with the context name, so that nested commands
   are looked up in that context's table (see `OO_DEFINE_ARGS`).
4. Branch semantics (arms) are only for real conditionals. Follow the `if` and
   `switch` handlers, and remember:
   - The probe goes at the very start of the arm body: `::mocktcl::_b <id>; `
   - An implicit arm, when you add one, must return "" and must not change semantics.
5. If the command also takes an *expression* (like the condition of `while`),
   register that word in `EXPR_ARGS` the same way. Its `&&`/`||` operands and
   `?:` conditions then get condition probes.
6. Add tests in `tests/test_instrument.py`:
   - The instrumented text has exactly the same number of lines as the original.
   - Running it under `tclsh` gives the same result as the original.
   - The manifest has the expected executable lines and branch arms.
7. Run the `dev-test` skill.
