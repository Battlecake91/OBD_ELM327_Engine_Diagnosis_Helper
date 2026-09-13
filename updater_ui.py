from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from update_service import (
    check_for_update,
    download_update_asset,
    portable_update_available,
    start_portable_update,
)


def install_update_menu(window, current_version: str) -> None:
    menu = window.menuBar().addMenu("Hilfe")
    action = menu.addAction("Nach Updates suchen …")

    def check() -> None:
        if not portable_update_available():
            QMessageBox.information(
                window,
                "Updater",
                "Der Selbst-Updater ist nur in einem gepackten Release aktiv. "
                "Beim Start aus dem Quellcode wird das Repository nicht überschrieben.",
            )
            return
        try:
            info = check_for_update(current_version)
        except Exception as exc:
            QMessageBox.critical(window, "Update-Prüfung fehlgeschlagen", str(exc))
            return
        if not info.is_newer:
            QMessageBox.information(
                window,
                "Kein Update",
                f"Installierte Version: {info.current_version}\n"
                f"Aktuelles Release: {info.latest_version}",
            )
            return

        answer = QMessageBox.question(
            window,
            "Update verfügbar",
            f"Version {info.latest_version} ist verfügbar.\n\n"
            f"Datei: {info.asset.name}\n\n"
            "Jetzt herunterladen und installieren? Die Anwendung wird neu gestartet.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        progress = QProgressDialog("Update wird heruntergeladen …", "Abbrechen", 0, 100, window)
        progress.setWindowTitle("ELM327 Diagnose-Helper aktualisieren")
        progress.setMinimumDuration(0)
        progress.setAutoClose(False)

        def on_progress(downloaded: int, total: int) -> None:
            progress.setValue(int(downloaded * 100 / total) if total else 0)
            QApplication.processEvents()
            if progress.wasCanceled():
                raise RuntimeError("Update wurde abgebrochen.")

        try:
            archive = download_update_asset(info, on_progress)
            progress.setLabelText("Updater wird gestartet …")
            progress.setValue(100)
            QApplication.processEvents()
            start_portable_update(archive)
        except Exception as exc:
            progress.close()
            QMessageBox.critical(window, "Update fehlgeschlagen", str(exc))
            return

        progress.close()
        QApplication.quit()

    action.triggered.connect(check)
