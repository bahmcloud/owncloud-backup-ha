# owncloud-backup-ha

Home Assistant custom integration that adds **ownCloud (Classic/Server)** as a **Backup Location / Backup Agent** using the official **WebDAV** interface.

This integration allows you to:
- store Home Assistant backups in ownCloud via WebDAV
- list backups stored in ownCloud from within the Home Assistant UI
- download and **restore** backups via the Home Assistant UI
- authenticate using **either** an ownCloud **App Password** (recommended for 2FA) **or** the regular account password

> **Status:** `0.2.0`  
> This release focuses on reliability and compatibility across Home Assistant versions.

---

## Features

- ✅ Home Assistant **Backup Agent** implementation (Backup Location)
- ✅ **Upload** backups to ownCloud via WebDAV
- ✅ **List** backups from ownCloud in HA UI
- ✅ **Download / Restore** backups via HA UI (streaming download)
- ✅ **Delete** backups from ownCloud
- ✅ Automatic DAV endpoint detection for ownCloud Classic:
  - `/remote.php/dav/files/<user>/`
  - `/remote.php/webdav/`
- ✅ Metadata sidecar (`.json`) for reliable listing + fallback when metadata is missing
- ✅ Supports **App Password** and **standard login**
- ✅ English UI & documentation
- ✅ HACS-ready repository structure

### Upload reliability (important)
To improve reliability behind reverse proxies and avoid WebDAV timeouts with chunked uploads,
the integration **spools the backup to a temporary file** and then uploads it with a proper
**Content-Length** header.

### Home Assistant compatibility
Home Assistant has evolved its backup metadata schema over time. This integration normalizes
backup metadata keys to remain compatible across multiple Home Assistant versions.

---

## Requirements

- Home Assistant version that supports the modern Backup system with backup agents (2025.x+).
- ownCloud Classic / Server with WebDAV enabled (default in ownCloud).

---

## Installation (HACS)

### Add as a custom repository
1. In Home Assistant: **HACS → Integrations → ⋮ → Custom repositories**
2. Add your repository URL
3. Category: **Integration**
4. Install **owncloud-backup-ha**
5. Restart Home Assistant

> This repository includes a `hacs.json` and follows the required `custom_components/` layout.

---

## Installation (Manual)

1. Copy the folder `custom_components/owncloud_backup/` into your Home Assistant config directory:
   - `<config>/custom_components/owncloud_backup/`
2. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to:
   - **Settings → Devices & services → Add integration**
2. Search for:
   - **ownCloud Backup (WebDAV)**
3. Enter:
   - **Base URL** (example: `https://cloud.example.com`)
   - **Username**
   - **Password / App Password**
   - **Backup folder path** (default: `/HomeAssistant/Backups`)
   - **Verify SSL** (default: enabled)

### Recommended authentication
- If you use **2FA**, create an **App Password** and use it as the "Password" field.
- If you do **not** use 2FA, your standard login password should also work.

---

## How backups are stored in ownCloud

The integration uploads:
- the backup tarball: `ha_backup_<backup_id>.tar`
- a metadata file: `ha_backup_<backup_id>.json`

The JSON metadata enables reliable listing and display in the HA UI.

If the JSON metadata is missing (e.g., you manually copied a `.tar`), the integration will still try to show the backup using WebDAV file properties (size + last modified time) as a fallback.

---

## Restore workflow (UI)

1. **Settings → System → Backups**
2. Select a backup from the ownCloud location
3. Choose **Restore**

Home Assistant will download the `.tar` from ownCloud using the Backup Agent API (streaming).

---

## Troubleshooting

### "Upload failed" / HTTP 504 (Gateway Timeout)
A 504 typically indicates a reverse proxy / gateway timeout (e.g., Nginx/Traefik/Cloudflare).
This integration uploads with Content-Length (non-chunked) for better compatibility.

If you still see 504:
- Increase proxy timeouts (e.g. `proxy_read_timeout`, `proxy_send_timeout` in Nginx)
- Ensure large uploads are allowed (`client_max_body_size` in Nginx)
- Avoid buffering restrictions for WebDAV endpoints

### "Cannot connect"
- Check your **Base URL**
- Make sure the ownCloud user can access WebDAV
- If you use 2FA, try an **App Password**
- Verify that your reverse proxy does not block `PROPFIND`, `MKCOL`, or `DELETE`

### SSL / certificate issues
- If you use a self-signed certificate, either:
  - install the CA properly, or
  - temporarily disable **Verify SSL** (not recommended for production)

---

## Security notes

- Credentials are stored in Home Assistant config entry storage.
- Prefer **App Passwords** over your main login password, especially with 2FA enabled.

---

## Development notes

This integration intentionally does not depend on external Python packages to keep deployment simple.
