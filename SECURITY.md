# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in market_analyzer, please report it responsibly:

1. **Do NOT open a public issue.**
2. Email: [your-email@example.com] with details.
3. Include: steps to reproduce, affected version, potential impact.
4. We will respond within 48 hours.

## Credential Safety

market_analyzer handles broker credentials. We take this seriously:

- Credentials are NEVER stored in code or committed to git
- `.env` and `broker.yaml` are in `.gitignore`
- The setup wizard saves credentials to `~/.market_analyzer/` with restrictive permissions (0o600)
- No credentials are ever logged or included in error messages

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.3.x   | Yes       |
| < 0.3   | No        |
