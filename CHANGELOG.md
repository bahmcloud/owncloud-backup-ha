# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project adheres to Semantic Versioning.

## [0.2.0] - 2026-01-14
### Added
- Improved cross-version compatibility with Home Assistant backup metadata by normalizing backup schema fields (e.g., `addons`, `database_included`, etc.).
- More robust metadata serialization for `AgentBackup` across Home Assistant versions (supports different serialization methods).

### Fixed
- Improved upload reliability by spooling backup streams to a temporary file and uploading with Content-Length (avoids chunked WebDAV uploads that may cause reverse proxy 504 timeouts).
- Added non-restrictive client timeouts for long-running WebDAV operations to prevent client-side aborts.
- Fixed backup listing failures caused by missing expected metadata keys in different Home Assistant versions.

## [0.1.1-alpha] - 2026-01-14
### Fixed
- Improved upload reliability by spooling backup streams to a temporary file and uploading with Content-Length (avoids chunked WebDAV uploads that may cause reverse proxy 504 timeouts).
- Set a non-restrictive client timeout for WebDAV PUT requests to prevent client-side premature aborts on slow connections.

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
