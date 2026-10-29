# Security Policy

## Supported versions

Security fixes go into the latest release of `actingweb` on PyPI. Please
upgrade to the newest version before reporting.

## Reporting a vulnerability

Please do **not** open a public GitHub issue for a security problem.

Report it privately by email to **support@actingweb.io**. Include the
affected version, the database backend (DynamoDB or PostgreSQL), and a
reproducer if you have one.

Fixed vulnerabilities are listed under `SECURITY` in
[CHANGELOG.rst](CHANGELOG.rst).

## Automated scanning

This project is enrolled in Anthropic's
[OSS Scanner](https://github.com/anthropics/oss-scanner); its build and
threat model live in [`.oss-scanner/`](.oss-scanner/). Reports from the
scanner also go to support@actingweb.io.
