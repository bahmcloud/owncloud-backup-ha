# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.1.0-alpha] - 2026-01-14
### Added
- Initial alpha release
- ownCloud Classic WebDAV backup agent for Home Assistant
- Backup upload, list, download/restore, and delete via Home Assistant UI
- Automatic DAV endpoint detection:
  - `/remote.php/dav/files/<user>/`
  - `/remote.php/webdav/`
- Support for app passwords and standard credentials (2FA compatible)
- Metadata sidecar (`.json`) with fallback listing from `.tar` properties
- HACS compatible repository structure
- English UI strings and documentation
