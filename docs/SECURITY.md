# Security Policy

## Supported Versions

Biodynamic Calendar is currently pre-1.0. Security fixes are handled on the
current `trunk` branch unless a release branch is explicitly announced.

## Reporting a Vulnerability

Please do not open a public issue for suspected security vulnerabilities.

Report privately by email:

```text
mot.yelraf@gmail.com
```

Include, when possible:

- A description of the issue.
- Steps to reproduce.
- The affected version or commit.
- Any local configuration needed to trigger the issue.
- Whether the issue affects the library, the FastAPI app, installers, or local
  storage.

## Scope

Security-relevant areas include:

- FastAPI routes and request handling.
- Local file reads and writes under `~/.biodynamic_calendar/`.
- Import, install, and deployment scripts.
- Handling of environment variables and configured file paths.
- Exposure of the local web app on a network interface.
- Dependency vulnerabilities that are reachable in normal use.

The project is a local-first tool. It is not designed to be exposed directly to
the public internet. If you run the app on a LAN or remote host, use operating
system firewall controls or a trusted reverse proxy appropriate for your setup.
The desktop launcher binds its owned FastAPI server to `0.0.0.0:8765` by
default. Set `BD_CALENDAR_HOST=127.0.0.1` before launching when LAN access is
not wanted.

## Response Expectations

This is a small maintainer-led project. I will make a good-faith effort to:

- Acknowledge useful reports promptly.
- Reproduce and assess the issue.
- Fix confirmed vulnerabilities before public disclosure when practical.
- Credit reporters when requested and appropriate.

Reports that rely on unsupported deployment patterns, require physical access to
the user's machine, or describe only theoretical dependency issues may be treated
as hardening suggestions rather than vulnerabilities.

## Public Disclosure

Please allow reasonable time for assessment and a fix before publishing details.
If the issue is accepted, disclosure timing will be coordinated with the
reporter where practical.
