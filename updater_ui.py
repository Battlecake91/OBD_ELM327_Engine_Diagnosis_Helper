from __future__ import annotations

from diagnostic_data import translations

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from update_service import (
    check_for_update,
    download_update_asset,
    portable_update_available,
    start_portable_update,
)


def install_update_menu(window, current_version: str) -> None:
    tr = translations()
    menu = window.menuBar().addMenu(tr.get("menu.help", "Help"))
    action = menu.addAction(tr.get("update.check", "Check for updates …"))

    def check() -> None:
        if not portable_update_available():
            QMessageBox.information(
                window,
                tr.get("update.title", "Updater"),
                tr.get("update.packaged_only", "Self-update is only active in a packaged release."),
            )
            return
        try:
            info = check_for_update(current_version)
        except Exception as exc:
            QMessageBox.critical(window, tr.get("update.check_failed", "Update check failed"), str(exc))
            return
        if not info.is_newer:
            QMessageBox.information(
                window,
                tr.get("update.none_title", "No update"),
                tr.get("update.none", "Installed version: {current}\\nLatest release: {latest}").format(current=info.current_version, latest=info.latest_version),
            )
            return

        answer = QMessageBox.question(
            window,
            tr.get("update.available_title", "Update available"),
            tr.get("update.available", "Version {latest} is available.\\n\\nFile: {asset}\\n\\nDownload and install now?").format(latest=info.latest_version, asset=info.asset.name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog(tr.get("update.downloading", "Downloading update …"), tr.get("update.cancel", "Cancel"), 0, 100, window)
        progress.setWindowTitle(tr.get("update.progress_title", "Update ELM327 Diagnosis Helper"))
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)

        def on_progress(downloaded: int, total: int) -> None:
            progress.setValue(int(downloaded * 100 / total) if total else 0)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError(tr.get("update.cancelled", "Update was cancelled."))

        try:
            archive = download_update_asset(info, on_progress)
            progress.setLabelText(tr.get("update.starting", "Starting updater …"))
            progress.setValue(100)
            QApplication.processEvents()
            start_portable_update(archive)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(window, tr.get("update.failed", "Update failed"), str(exc))
            return

        progress.close()
        QApplication.quit()

    action.triggered.connect(check)
