# Security Policy

## Reporting a vulnerability

If you think you've found a security issue, **please don't open a public issue** or discuss it in forums. Contact us **privately** at:

**h2aichat.com@gmail.com**

(Alternatively, use GitHub's private Security Advisories for this repository.)

If you can, include: which version, how to reproduce it, and the impact you believe it has. We'll get back to you as soon as we can and keep you posted on the fix. We appreciate responsible disclosure and will credit you if you'd like.

## Supported versions

We provide security support for the **latest released version**. As a young project, we don't yet maintain older release branches.

## Good practices when deploying

- Never commit real keys to the repository; use environment variables (see `.env.example`).
- If you use local models for confidential data, use **models from recognized sources** and avoid enabling "trust remote code" from unknown authors.
