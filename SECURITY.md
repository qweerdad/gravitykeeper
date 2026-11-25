# Security

Report suspected vulnerabilities through the repository's private security reporting channel when available. Include the version, impact and a synthetic reproduction. Keep real transcripts, credentials, workstation paths and project archives out of public issues.

GravityKeeper reads known local data paths, does not contact Antigravity APIs, and never writes a conversation to Antigravity. Backup/archive tampering checks use SHA-256 and ZIP CRC. Checksums verify consistency against the supplied list. They do not authenticate an untrusted distribution or encrypt a backup.

Report failures that allow source modification, unsafe path handling, accidental disclosure, or incorrect completeness verdicts.
