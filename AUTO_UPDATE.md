# GitHub Releases automatic updates

Repository: https://github.com/woong-sung/SWFTP

The Windows executable checks the latest stable Release when it starts. When a newer version is available, it asks for confirmation. On OK it downloads `SFTP_Client.exe`, verifies the GitHub asset SHA-256 digest and size, waits for active operations to finish, then closes, installs and automatically restarts the application. Cancel skips the update for this launch. Active transfers retain the existing close protection. The old executable is saved as `SFTP_Client.exe.previous`. Startup continues normally if the update check fails.

## Publish a version

1. Increase `APP_VERSION` in `app_version.py` (MAJOR.MINOR.PATCH).
2. Run `python -m unittest test_auto_update test_directory_upload`.
3. Run `python -m PyInstaller --noconfirm SFTP_Client.spec`.
4. Create a published, stable GitHub Release with a matching tag such as `v1.1.1`.
5. Attach `dist/SFTP_Client.exe` using that exact filename. GitHub must provide the asset SHA-256 digest.

Install the initial updater-enabled executable once. Subsequent higher versions prompt for confirmation and restart automatically after installation. Do not rename the Release asset. The install folder must be writable by the current user.

This configuration uses unauthenticated public Releases. A private repository needs a separate authentication/distribution design; do not embed a GitHub token in the executable. No release is published by building locally.

GitHub API reference: https://docs.github.com/en/rest/releases/releases#get-the-latest-release
