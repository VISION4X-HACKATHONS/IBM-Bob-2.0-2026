# Workflow

The supported path is: change request and explicit repository path, repository scan, evidence-backed impact result, implementation plan, verification, and final report. Analysis and verification records are stored in SQLite and can be reloaded by the frontend. Verification reports the actual working directory, command, exit code, output, and parsed test counts when available; discovery and infrastructure problems are not reported as regression failures.
