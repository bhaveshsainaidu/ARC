# Security Policy for ARC

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 5.0.x   | :white_check_mark: |
| < 5.0   | :x:                |

---

## 🔒 Privacy & Security Guarantees

ARC is designed with a **privacy-first, local-first paradigm**:

1. **Zero-Leak Policy**: All log outputs (`logs/arc.log`) are filtered through automated regex sanitizers that strip Gemini API keys, Bearer tokens, private tokens, and binary payloads.
2. **Encryption At Rest**: Personal configuration, episodic memories, and healthcare records are encrypted with Fernet AES-128-CBC derived via PBKDF2-HMAC-SHA256 bound to hardware identifiers.
3. **Explicit Consent Matrix**: Critical capabilities (camera access, continuous microphone, shell execution, screen recording) require explicit user consent via `actions/consent_manager.py`.
4. **Local Subprocess Isolation**: Code helper execution runs within restricted timeouts and subprocess sandboxes with resource capping.

---

## 🚨 Reporting a Vulnerability

If you discover a security vulnerability or potential data leak in ARC, please do **NOT** open a public issue.

Instead, please send an email directly to:
**gantabhaveshsainaidu@gmail.com**

Please include:
- A description of the vulnerability and attack vector.
- Steps or a minimal script to reproduce the issue.
- Potential impact and affected subsystems.

You will receive a response within 48 hours, and a coordinated disclosure timeline will be established.
