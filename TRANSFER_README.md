# MVP source snapshot — read this first

This is an existing MVP source snapshot, not a hosted website or a preinstalled executable.
Start with PROJECT_HANDOFF.md, then read the repository README and project instructions.

The snapshot includes current uncommitted remediation files, tests, migrations, synthetic data,
and historical screenshots. It excludes private configuration, keys, tokens, database contents,
dependencies, build outputs, logs, Git history, and Claude-specific launcher configuration.

Original branch: fix/audit-remediation. Last observed commit: 4d260d3.
The archive contains newer working-tree contents, not only that commit.

No API key is needed for deterministic explanations. Gemini needs separately supplied private
credentials and correct backend environment configuration. Do not paste keys into a new chat.

The original running demo uses database ddc_e2e and ports 3010/8010. Tests can erase data:
use a new dedicated verification database and different ports. localhost is not a public URL.

The original handoff and SOURCE_MANIFEST.json describe the untouched archive baseline. The working copy now
contains independently verified fixes and additional tests; see docs/VERIFICATION.md for current evidence and
remaining gaps. SOURCE_MANIFEST.json is retained as provenance, not a checksum list of the modified working copy.

The source snapshot originally excluded dependencies and databases. This local working copy also has ignored
verification dependencies, private test configuration and isolated database files. Exclude those when packaging.
