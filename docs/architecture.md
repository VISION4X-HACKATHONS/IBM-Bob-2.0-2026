# Architecture

The prototype is local-first. The React client calls FastAPI, which invokes the analyzer against a repository path inside the workspace. The analyzer produces evidence from files, Python AST symbols, imports, manifests, route calls, tests, configuration, and database-related filenames. Impact analysis selects evidence using request terms and emits a plan without modifying source files.

The implementation boundary is intentionally controlled: analysis and verification are available through APIs; implementation approval and file mutation remain explicit future work.
