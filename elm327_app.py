#!/usr/bin/env python3
"""ELM327 Live Diagnostic 3.1 entry point with persistent profiles."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from PySide6.QtCore import QSettings, QThread, Qt, Signal, Slot
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem
from elm327_twingo_gui import APP_NAME, DESKTOP_FILE_ID, ORGANIZATION_NAME, SENSORS, MainWindow as BaseWindow, TestStage
APP_VERSION = '3.1.0'
MAC_RE = re.compile('(?:[0-9A-F]{2}:){5}[0-9A-F]{2}')

def stage_dict(stage: TestStage) -> dict:
    return dict(name=stage.name, instruction=stage.instruction, duration_s=stage.duration_s, target_rpm=stage.target_rpm, tolerance_rpm=stage.tolerance_rpm, manual=stage.manual)

def stage_value(value: object) -> TestStage | None:
    if not isinstance(value, dict):
        return None
    try:
        target = value.get('target_rpm')
        return TestStage(str(value.get('name', 'Stage')) or 'Stage', str(value.get('instruction', '')), max(0.0, float(value.get('duration_s', 0))), None if target in (None, '') else int(target), max(0, int(value.get('tolerance_rpm', 100))), bool(value.get('manual', False)))
    except (TypeError, ValueError):
        return None

class BluetoothScanner(QThread):
    ready = Signal(object)
    failed = Signal(str)

    @staticmethod
    def parse(text: str) -> list[dict[str, str]]:
        found, seen = ([], set())
        for line in text.splitlines():
            match = re.match('^Device\\s+((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?:\\s+(.+))?$', line.strip())
            if not match:
                continue
            address = match.group(1).upper()
            if address in seen:
                continue
            seen.add(address)
            found.append({'address': address, 'name': (match.group(2) or 'Bluetooth device').strip()})
        return found

    def run(self) -> None:
        tool = shutil.which('bluetoothctl')
        if sys.platform != 'linux' or not tool:
            self.failed.emit('Bluetooth discovery requires Linux and bluetoothctl.')
            return
        try:
            output = ''
            for command in ([tool, 'devices', 'Paired'], [tool, 'devices']):
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=12, check=False)
                output += '\n' + result.stdout
                if self.parse(result.stdout):
                    break
            self.ready.emit(self.parse(output))
        except Exception as exc:
            self.failed.emit(str(exc))

class MainWindow(BaseWindow):

    def __init__(self):
        settings = QSettings(ORGANIZATION_NAME, APP_NAME)
        self.pid_presets = self._read_pid_presets(settings)
        self.test_profiles = self._read_test_profiles(settings)
        self.saved_bt = self._read_bt(settings)
        self.discovered_bt: list[dict] = []
        self.bt_scanner: BluetoothScanner | None = None
        self.PID_PRESETS = self.pid_presets
        self.TEST_PRESETS = {name: list(profile['stages']) for name, profile in self.test_profiles.items()}
        self.profile_ready = False
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} {APP_VERSION}')
        self._add_pid_controls()
        self._add_test_editor()
        self._add_bt_selector()
        self._restore_extra()
        self.profile_ready = True
        self._connect_extra()
        self._save_settings()

    @staticmethod
    def _json(settings: QSettings, key: str, fallback):
        try:
            return json.loads(str(settings.value(key, '')))
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback

    def _read_pid_presets(self, settings: QSettings) -> dict[str, list[str]]:
        defaults = {name: list(keys) for name, keys in BaseWindow.PID_PRESETS.items()}
        raw, valid = (self._json(settings, 'profiles/pids_v1', {}), {s.key for s in SENSORS})
        if not isinstance(raw, dict):
            return defaults
        result = {str(name): [str(k) for k in keys if str(k) in valid] for name, keys in raw.items() if isinstance(keys, list)}
        result = {n: k for n, k in result.items() if n and k}
        if not result:
            return defaults
        result.setdefault('Balanced', defaults['Balanced'])
        return result

    def _read_test_profiles(self, settings: QSettings) -> dict[str, dict]:
        defaults = {name: {'pid': '', 'stages': list(stages)} for name, stages in BaseWindow.TEST_PRESETS.items()}
        for name in ('RPM step test', 'Extended fuel-trim test', 'Oxygen-sensor response'):
            defaults[name]['pid'] = 'Lean diagnostics'
        defaults['Electrical load test']['pid'] = 'Balanced'
        raw = self._json(settings, 'profiles/tests_v1', {})
        if not isinstance(raw, dict):
            return defaults
        result = {}
        for name, profile in raw.items():
            if not isinstance(profile, dict):
                continue
            stages = [stage_value(item) for item in profile.get('stages', [])]
            stages = [stage for stage in stages if stage]
            if stages:
                result[str(name)] = {'pid': str(profile.get('pid', '')), 'stages': stages}
        return result or defaults

    def _read_bt(self, settings: QSettings) -> list[dict]:
        raw = self._json(settings, 'bluetooth/saved_v1', [])
        if not isinstance(raw, list):
            return []
        result = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            address = str(item.get('address', '')).upper()
            if not MAC_RE.fullmatch(address):
                continue
            try:
                channel = max(1, min(30, int(item.get('channel', 1))))
            except (TypeError, ValueError):
                channel = 1
            result.append({'address': address, 'name': str(item.get('name', 'OBD-II adapter')), 'channel': channel})
        return result

    def _add_pid_controls(self) -> None:
        row = QHBoxLayout()
        group = self.pid_preset_combo.parentWidget()
        for text, callback in (('New', self._new_pid), ('Save / update', self._save_pid), ('Delete', self._delete_pid), ('Restore defaults', self._restore_pid)):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        self.pid_state = QLabel()
        row.addWidget(self.pid_state)
        row.addStretch()
        group.layout().insertLayout(1, row)
        selected = str(self.settings.value('pids/active_preset', ''))
        self._refresh_pid_combo(selected or 'Custom')
        self._sync_pid_combo(force_match=not bool(selected))

    def _add_test_editor(self) -> None:
        layout = self.test_preset_combo.parentWidget().layout()
        self.test_pid_combo = QComboBox()
        self._refresh_test_pid_combo()
        layout.addWidget(QLabel('PID preset:'), 1, 0)
        layout.addWidget(self.test_pid_combo, 1, 1, 1, 3)
        for column, (text, callback) in enumerate((('New', self._new_test), ('Save', self._save_test), ('Delete', self._delete_test)), start=4):
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button, 1, column)
        self.stage_table = QTableWidget(0, 6)
        self.stage_table.setHorizontalHeaderLabels(['Stage', 'Instruction', 'Duration [s]', 'Target RPM', 'Tolerance', 'Manual'])
        self.stage_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.stage_table, 2, 0, 1, 8)
        row = QHBoxLayout()
        for text, callback in (('Add stage', self._add_stage), ('Remove stage', self._remove_stage), ('Move up', lambda: self._move_stage(-1)), ('Move down', lambda: self._move_stage(1))):
            button = QPushButton(text)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row, 3, 0, 1, 8)
        selected = str(self.settings.value('tests/profile', ''))
        index = self.test_preset_combo.findText(selected)
        if index >= 0:
            self.test_preset_combo.setCurrentIndex(index)
        self._load_test(self.test_preset_combo.currentText())

    def _add_bt_selector(self) -> None:
        old, layout = (self.bluetooth_address_edit, self.bluetooth_address_edit.parentWidget().layout())
        self.bt_combo = QComboBox()
        self.bt_combo.setEditable(True)
        self.bt_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        layout.replaceWidget(old, self.bt_combo)
        old.hide()
        for column, (text, callback) in enumerate((('Refresh devices', self._scan_bt), ('Save adapter', self._save_bt), ('Remove adapter', self._remove_bt)), start=4):
            button = QPushButton(text)
            button.clicked.connect(callback)
            layout.addWidget(button, 0, column)
            if text.startswith('Refresh'):
                self.bt_refresh = button
            elif text.startswith('Save'):
                self.bt_save = button
            else:
                self.bt_remove = button
        self._populate_bt(str(self.settings.value('bluetooth/address', '')))
        if sys.platform != 'linux':
            self.bt_refresh.setEnabled(False)


    def _set_connection_controls(self, enabled: bool) -> None:
        super()._set_connection_controls(enabled)
        if not hasattr(self, 'bt_combo'):
            return
        linux_available = enabled and sys.platform == 'linux'
        self.bt_combo.setEnabled(enabled)
        self.bluetooth_channel_spin.setEnabled(enabled)
        self.rfcomm_device_edit.setEnabled(enabled)
        self.bt_refresh.setEnabled(linux_available)
        self.bt_save.setEnabled(enabled)
        self.bt_remove.setEnabled(enabled)

    def _connect_extra(self) -> None:
        for signal in (self.tabs.currentChanged, self.history_combo.currentIndexChanged, self.port_combo.currentIndexChanged, self.baud_combo.currentTextChanged, self.protocol_combo.currentIndexChanged, self.poll_pause_spin.valueChanged, self.command_timeout_spin.valueChanged, self.target_rpm_spin.valueChanged, self.tolerance_spin.valueChanged, self.hold_time_spin.valueChanged, self.test_pid_combo.currentIndexChanged, self.bluetooth_channel_spin.valueChanged, self.rfcomm_device_edit.textChanged):
            signal.connect(self._save_settings)
        self.test_preset_combo.currentIndexChanged.connect(self._test_changed)
        self.pid_preset_combo.currentTextChanged.connect(self._pid_preset_selected)
        self.bt_combo.currentIndexChanged.connect(self._bt_changed)
        self.bt_combo.editTextChanged.connect(self._bt_changed)

    def _restore_extra(self) -> None:
        geometry = self.settings.value('ui/geometry')
        if geometry:
            self.restoreGeometry(geometry)
        self.tabs.setCurrentIndex(max(0, min(self.tabs.count() - 1, int(self.settings.value('ui/tab', 0)))))
        index = self.history_combo.findData(int(self.settings.value('plot/window', 600)))
        if index >= 0:
            self.history_combo.setCurrentIndex(index)
        self.target_rpm_spin.setValue(int(self.settings.value('tests/target', self.target_rpm_spin.value())))
        self.tolerance_spin.setValue(int(self.settings.value('tests/tolerance', self.tolerance_spin.value())))
        self.hold_time_spin.setValue(int(self.settings.value('tests/hold', self.hold_time_spin.value())))

    def _save_settings(self, *_args) -> None:
        if not getattr(self, 'profile_ready', False):
            return
        self.bluetooth_address_edit.setText(self._bt_address())
        super()._save_settings()
        self.settings.setValue('ui/geometry', self.saveGeometry())
        self.settings.setValue('ui/tab', self.tabs.currentIndex())
        self.settings.setValue('plot/window', self.history_combo.currentData())
        self.settings.setValue('tests/profile', self.test_preset_combo.currentText())
        self.settings.setValue('tests/target', self.target_rpm_spin.value())
        self.settings.setValue('tests/tolerance', self.tolerance_spin.value())
        self.settings.setValue('tests/hold', self.hold_time_spin.value())
        self.settings.setValue('pids/active_preset', self.pid_preset_combo.currentText())
        self.settings.setValue('profiles/pids_v1', json.dumps(self.pid_presets, ensure_ascii=False))
        tests = {name: {'pid': profile['pid'], 'stages': [stage_dict(stage) for stage in profile['stages']]} for name, profile in self.test_profiles.items()}
        self.settings.setValue('profiles/tests_v1', json.dumps(tests, ensure_ascii=False))
        self.settings.setValue('bluetooth/saved_v1', json.dumps(self.saved_bt, ensure_ascii=False))
        self.settings.sync()

    def _refresh_pid_combo(self, selected='') -> None:
        selected = selected or self.pid_preset_combo.currentText()
        self.pid_preset_combo.blockSignals(True)
        self.pid_preset_combo.clear()
        self.pid_preset_combo.addItems(sorted(self.pid_presets))
        self.pid_preset_combo.addItem('Custom')
        index = self.pid_preset_combo.findText(selected)
        self.pid_preset_combo.setCurrentIndex(index if index >= 0 else self.pid_preset_combo.count() - 1)
        self.pid_preset_combo.blockSignals(False)
        if hasattr(self, 'test_pid_combo'):
            self._refresh_test_pid_combo()

    def _sync_pid_combo(self, force_match: bool = False) -> None:
        current = self.pid_preset_combo.currentText()
        if force_match or current not in self.pid_presets:
            current = next((name for name, keys in self.pid_presets.items() if set(keys) == self.enabled_keys), 'Custom')
            self.pid_preset_combo.blockSignals(True)
            self.pid_preset_combo.setCurrentText(current)
            self.pid_preset_combo.blockSignals(False)
        exact = current in self.pid_presets and set(self.pid_presets[current]) == self.enabled_keys
        self.pid_state.setText('Applied' if exact else 'Modified')

    def _pid_preset_selected(self, name: str) -> None:
        if getattr(self, 'profile_ready', False) and name in self.pid_presets:
            self._apply_selected_pid_preset()

    @Slot(QTableWidgetItem)
    def _pid_selection_changed(self, item) -> None:
        if item.column() != 0:
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if not key:
            return
        (self.enabled_keys.add if item.checkState() == Qt.CheckState.Checked else self.enabled_keys.discard)(str(key))
        if hasattr(self, 'pid_state'):
            self._sync_pid_combo()
        self._apply_pid_visibility()
        self._save_settings()
        if self.worker:
            self.worker.update_enabled_keys(self._effective_worker_keys())

    def _apply_selected_pid_preset(self) -> None:
        keys = self.pid_presets.get(self.pid_preset_combo.currentText())
        if not keys:
            return
        self.enabled_keys = set(keys)
        self.pid_table.blockSignals(True)
        for sensor in SENSORS:
            self.pid_table.item(self.pid_row_by_key[sensor.key], 0).setCheckState(Qt.CheckState.Checked if sensor.key in self.enabled_keys else Qt.CheckState.Unchecked)
        self.pid_table.blockSignals(False)
        self._apply_pid_visibility()
        self._sync_pid_combo()
        self._save_settings()
        if self.worker:
            self.worker.update_enabled_keys(self._effective_worker_keys())

    def _new_pid(self) -> None:
        name, ok = QInputDialog.getText(self, 'New PID preset', 'Name:')
        name = name.strip()
        if ok and name and (name not in self.pid_presets):
            self.pid_presets[name] = sorted(self.enabled_keys)
            self._refresh_pid_combo(name)
            self._sync_pid_combo()
            self._save_settings()

    def _save_pid(self) -> None:
        name = self.pid_preset_combo.currentText()
        if name == 'Custom':
            self._new_pid()
            return
        if name and self.enabled_keys:
            self.pid_presets[name] = sorted(self.enabled_keys)
            self._save_settings()
            self._sync_pid_combo()

    def _delete_pid(self) -> None:
        name = self.pid_preset_combo.currentText()
        if name == 'Balanced':
            QMessageBox.information(self, 'Required preset', 'Balanced is the fallback preset and can be edited, but not deleted.')
            return
        if name in self.pid_presets and len(self.pid_presets) > 1 and (QMessageBox.question(self, 'Delete preset', f"Delete '{name}'?") == QMessageBox.StandardButton.Yes):
            del self.pid_presets[name]
            for profile in self.test_profiles.values():
                if profile.get('pid') == name:
                    profile['pid'] = ''
            self._refresh_pid_combo('Custom')
            self._save_settings()

    def _restore_pid(self) -> None:
        self.pid_presets.update({name: list(keys) for name, keys in BaseWindow.PID_PRESETS.items()})
        self._refresh_pid_combo('Balanced')
        self._save_settings()

    def _refresh_test_pid_combo(self) -> None:
        current = self.test_pid_combo.currentData() if self.test_pid_combo.count() else ''
        self.test_pid_combo.clear()
        self.test_pid_combo.addItem('Current PID selection', '')
        for name in sorted(self.pid_presets):
            self.test_pid_combo.addItem(name, name)
        self.test_pid_combo.setCurrentIndex(max(0, self.test_pid_combo.findData(current)))

    def _write_stage(self, stage) -> None:
        row = self.stage_table.rowCount()
        self.stage_table.insertRow(row)
        for column, value in enumerate((stage.name, stage.instruction, f'{stage.duration_s:g}', '' if stage.target_rpm is None else str(stage.target_rpm), str(stage.tolerance_rpm))):
            self.stage_table.setItem(row, column, QTableWidgetItem(value))
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if stage.manual else Qt.CheckState.Unchecked)
        self.stage_table.setItem(row, 5, item)

    def _read_stages(self) -> list[TestStage]:
        result = []
        for row in range(self.stage_table.rowCount()):
            def cell(col: int) -> str:
                item = self.stage_table.item(row, col)
                return item.text().strip() if item else ''
            try:
                duration, target, tolerance = (max(0.0, float(cell(2) or 0)), int(cell(3)) if cell(3) else None, max(0, int(cell(4) or 100)))
            except ValueError as exc:
                raise ValueError(f'Invalid number in stage {row + 1}.') from exc
            manual = self.stage_table.item(row, 5).checkState() == Qt.CheckState.Checked
            if not manual and duration <= 0:
                raise ValueError(f'Stage {row + 1} needs a duration.')
            result.append(TestStage(cell(0) or f'Stage {row + 1}', cell(1), duration, target, tolerance, manual))
        return result

    def _load_test(self, name) -> None:
        profile = self.test_profiles.get(name)
        if not profile:
            return
        self.stage_table.setRowCount(0)
        for stage in profile['stages']:
            self._write_stage(stage)
        self.test_pid_combo.setCurrentIndex(max(0, self.test_pid_combo.findData(profile['pid'])))

    def _test_changed(self, *_args) -> None:
        self._load_test(self.test_preset_combo.currentText())
        self._save_settings()

    def _new_test(self) -> None:
        name, ok = QInputDialog.getText(self, 'New test routine', 'Name:')
        name = name.strip()
        if ok and name and (name not in self.test_profiles):
            self.test_profiles[name] = {'pid': '', 'stages': [TestStage('Idle baseline', 'Stabilise at idle.', 10)]}
            self.TEST_PRESETS[name] = self.test_profiles[name]['stages']
            self.test_preset_combo.addItem(name)
            self.test_preset_combo.setCurrentText(name)
            self._load_test(name)
            self._save_settings()

    def _save_test(self) -> None:
        try:
            stages = self._read_stages()
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid routine', str(exc))
            return
        name = self.test_preset_combo.currentText()
        if name and stages:
            self.test_profiles[name] = {'pid': str(self.test_pid_combo.currentData() or ''), 'stages': stages}
            self.TEST_PRESETS[name] = stages
            self._save_settings()

    def _delete_test(self) -> None:
        name = self.test_preset_combo.currentText()
        if name in self.test_profiles and len(self.test_profiles) > 1 and (QMessageBox.question(self, 'Delete routine', f"Delete '{name}'?") == QMessageBox.StandardButton.Yes):
            del self.test_profiles[name]
            self.TEST_PRESETS.pop(name, None)
            self.test_preset_combo.removeItem(self.test_preset_combo.currentIndex())
            self._load_test(self.test_preset_combo.currentText())
            self._save_settings()

    def _add_stage(self) -> None:
        self._write_stage(TestStage('New stage', '', 10))

    def _remove_stage(self) -> None:
        if self.stage_table.currentRow() >= 0:
            self.stage_table.removeRow(self.stage_table.currentRow())

    def _move_stage(self, direction) -> None:
        row, target = (self.stage_table.currentRow(), self.stage_table.currentRow() + direction)
        if row < 0 or target < 0 or target >= self.stage_table.rowCount():
            return
        try:
            stages = self._read_stages()
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid routine', str(exc))
            return
        stages[row], stages[target] = (stages[target], stages[row])
        self.stage_table.setRowCount(0)
        for stage in stages:
            self._write_stage(stage)
        self.stage_table.setCurrentCell(target, 0)

    def _start_selected_preset(self) -> None:
        try:
            stages = self._read_stages()
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid routine', str(exc))
            return
        pid = str(self.test_pid_combo.currentData() or '')
        if pid:
            self.pid_preset_combo.setCurrentText(pid)
            self._apply_selected_pid_preset()
        if self._ensure_rpm_for_test():
            self._start_test(stages, self.test_preset_combo.currentText() or 'Custom test')

    def _bt_address(self) -> str:
        match = MAC_RE.search(self.bt_combo.currentText().upper()) or MAC_RE.search(str(self.bt_combo.currentData() or '').upper())
        return match.group(0) if match else self.bt_combo.currentText().upper().strip()

    def _populate_bt(self, selected='') -> None:
        devices = {str(item['address']): item for item in self.saved_bt + self.discovered_bt}
        if selected and selected not in devices:
            devices[selected] = {'address': selected, 'name': 'Previously selected adapter'}
        self.bt_combo.blockSignals(True)
        self.bt_combo.clear()
        for address, item in sorted(devices.items(), key=lambda pair: str(pair[1].get('name', ''))):
            self.bt_combo.addItem(f"{item.get('name', 'Bluetooth device')} — {address}", address)
        index = self.bt_combo.findData(selected)
        self.bt_combo.setCurrentIndex(index if index >= 0 else -1)
        if selected and index < 0:
            self.bt_combo.setEditText(selected)
        self.bt_combo.blockSignals(False)
        self._bt_changed()

    def _bt_changed(self, *_args) -> None:
        address = self._bt_address()
        self.bluetooth_address_edit.setText(address)
        for item in self.saved_bt:
            if item['address'] == address:
                self.bluetooth_channel_spin.setValue(int(item['channel']))
                break
        self._save_settings()

    def _scan_bt(self) -> None:
        if self.bt_scanner and self.bt_scanner.isRunning():
            return
        self.bt_refresh.setEnabled(False)
        self.bt_scanner = BluetoothScanner(self)
        self.bt_scanner.ready.connect(self._bt_ready)
        self.bt_scanner.failed.connect(self.bluetooth_status_label.setText)
        self.bt_scanner.finished.connect(self._bt_finished)
        self.bt_scanner.start()

    @Slot(object)
    def _bt_ready(self, devices) -> None:
        self.discovered_bt = list(devices)
        self._populate_bt(self._bt_address())

    def _bt_finished(self) -> None:
        self.bt_scanner = None
        self.bt_refresh.setEnabled(not self.connected_state and sys.platform == 'linux')

    def _save_bt(self) -> None:
        address = self._bt_address()
        if not MAC_RE.fullmatch(address):
            QMessageBox.warning(self, 'Invalid address', 'Select or enter a valid MAC address.')
            return
        name, ok = QInputDialog.getText(self, 'Save adapter', 'Display name:', text='OBD-II adapter')
        if ok and name.strip():
            self.saved_bt = [item for item in self.saved_bt if item['address'] != address] + [{'address': address, 'name': name.strip(), 'channel': self.bluetooth_channel_spin.value()}]
            self._populate_bt(address)
            self._save_settings()

    def _remove_bt(self) -> None:
        self.saved_bt = [item for item in self.saved_bt if item['address'] != self._bt_address()]
        self._populate_bt('')
        self._save_settings()

    def closeEvent(self, event) -> None:
        self._save_settings()
        if self.bt_scanner and self.bt_scanner.isRunning():
            self.bt_scanner.requestInterruption()
            self.bt_scanner.wait(1000)
        super().closeEvent(event)

def main() -> int:
    app = QApplication(sys.argv)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    if hasattr(app, 'setDesktopFileName'):
        app.setDesktopFileName(DESKTOP_FILE_ID)
    icon = Path(__file__).resolve().parent / 'assets' / f'{DESKTOP_FILE_ID}.svg'
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    window = MainWindow()
    window.show()
    return app.exec()
if __name__ == '__main__':
    raise SystemExit(main())
