# Architecture

The application is local-first. The React client calls FastAPI, which invokes the analyzer against the user-provided repository path. The analyzer produces evidence from existing files, Python AST symbols, resolvable repository-local imports, manifests, route decorators, tests, configuration, and database-related files. Impact analysis selects request-matched files and their connected local imports, and emits a plan without modifying source files. Analysis and verification records are persisted in SQLite under `.codeguardian/`.

Verification discovers and runs tests with the analyzed repository as its working directory. Discovery errors, execution errors, no-test repositories, passing tests, and failing tests are distinct persisted states. The implementation boundary remains controlled: `/api/implement` retains its current approval-manifest behavior and does not modify source files.
