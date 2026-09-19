# Project Instructions

- Use the project virtual environment (`venv/bin/python`) for compilation checks, tests, and all change validation commands.
- Use the `logging` module instead of `print()` for application diagnostics.
- Use deferred logging formatting, such as `logger.info("Value: %s", value)`, instead of f-strings or string interpolation in log messages.
- Be less verbose in the chat messages. Avoid repeating and rewording the same information multiple times.
- Use short imperative sentences in the chat messages. Do not summarize changes and do not justify them.

## Code Parts Consistency

- Update SQL models for SqlAlchemy `power_herald\models.py`, schema definition `assets/schema.py`, client API `power_herald\cli.py`, and readme `README.md` files consistently.

