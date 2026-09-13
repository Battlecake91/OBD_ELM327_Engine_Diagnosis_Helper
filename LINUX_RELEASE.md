# Linux-Release

Ab Version 3.2 wird neben dem Windows-Build auch ein eigenständiger Linux-x86_64-Build erzeugt.

## GitHub Actions

Der Workflow .github/workflows/linux-release.yml:

1. installiert die benötigten Qt-/OpenGL-Systembibliotheken,
2. installiert die Python-Build-Abhängigkeiten,
3. führt die Tests headless aus,
4. baut Hauptprogramm und Updater mit PyInstaller,
5. erzeugt ein portables ZIP,
6. erzeugt SHA-256-Prüfsummen,
7. hängt die Linux-Dateien bei Tag-/manuellen Releases an das GitHub-Release an.

Das Release-ZIP enthält:

~~~text
OBD_ELM327_Engine_Diagnosis_Helper
OBD_ELM327_Updater
~~~

Beide Dateien werden ausführbar ausgeliefert.

## Selbst-Updater

Der Updater folgt demselben Prinzip wie unter Windows:

- neuestes GitHub-Release prüfen,
- passendes Linux-ZIP laden,
- Hauptprogramm beenden,
- Programmdateien austauschen,
- lokale Einstellungen und Update-Logs erhalten,
- Anwendung neu starten.

Beim Start aus dem Quellcode ist der Selbst-Updater absichtlich deaktiviert und verändert das Checkout nicht.
