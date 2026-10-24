# Security policy

## Report privately

Send security reports to
[hamza.457.shahbaz@gmail.com](mailto:hamza.457.shahbaz@gmail.com), the
maintainer contact published on Cubeon's website. Use a subject such as
`Cubeon security report: <affected component>`.

Do not put an undisclosed vulnerability, exploit, credential, or private
player data in a public issue or pull request. If the report requires an
encrypted transfer, first ask the maintainer to arrange a suitable channel;
do not send sensitive material in the initial message.

## What to include

- Affected component: launcher, companion mod, Worker, or download service.
- Cubeon version, commit, operating system, and relevant configuration.
- The security impact and any prerequisites for exploitation.
- Minimal reproduction steps or a proof of concept using test data.
- Whether the report has been shared elsewhere.

Remove real credentials and player identity data. A redacted sample is
preferable to an entire log, cache, or launcher directory.

## Version information

Use the current release or `main` when checking a report, and list any older
versions known to be affected. If the problem only exists in a packaged
build, identify the exact artifact and download source.

Hosted Workers and downloadable clients can change independently. Include
the service route and observation time for a backend issue, without
publishing secrets or private request contents.

## Safe investigation

Use local test accounts and environments you control. Do not access another
player's data, disrupt live services, or perform unbounded load testing.
If an investigation exposes private data, stop and report the observation
without collecting additional records.

## Disclosure

Allow the maintainer to assess the report and coordinate a fix before
publishing exploit details. This policy does not promise a response deadline,
a remediation deadline, or a monetary reward.

For non-security bugs and feature proposals, use
[GitHub Issues](https://github.com/Shadow-457/Cubeon/issues) and the
[contribution guide](CONTRIBUTING.md).
