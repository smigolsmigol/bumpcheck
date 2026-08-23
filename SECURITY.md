# Security policy

## Supported versions

Only the latest Bumpcheck release receives security fixes.

## Reporting a vulnerability

Please do not open a public issue. Email `smigolsmigol@protonmail.com` with the
affected Bumpcheck version, the impact, and a minimal reproduction. Remove any
credentials, personal data, or other secrets before sending the report.

Bumpcheck runs case files and installs requested packages with the invoking
user's permissions. These are trusted inputs; Bumpcheck is not a security
sandbox. A report should identify behavior that crosses this documented trust
boundary.

Report vulnerabilities in third-party dependencies to the relevant upstream
project unless Bumpcheck-specific behavior changes their impact.
