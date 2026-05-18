from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from time import monotonic

import qt
import slicer
from slicer.i18n import tr as _
from slicer.i18n import translate
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin
import vtkSegmentationCorePython as vtkSegmentationCore


SETTINGS_ROOT = "WorkAudit"
DEFAULT_IDLE_TIMEOUT_SECONDS = 90


def utcnow_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def workaudit_dir():
    settings_path = Path(slicer.app.slicerUserSettingsFilePath).resolve().parent
    return settings_path / SETTINGS_ROOT


def session_log_path():
    return workaudit_dir() / "sessions.jsonl"


@dataclass
class ActivityAccumulator:
    idle_timeout_seconds: int
    accumulated_seconds: float = 0.0
    last_activity_monotonic: float | None = None
    idle_gap_count: int = 0

    def note_activity(self, now_monotonic: float):
        if self.last_activity_monotonic is not None:
            gap = max(0.0, now_monotonic - self.last_activity_monotonic)
            self.accumulated_seconds += min(gap, self.idle_timeout_seconds)
            if gap > self.idle_timeout_seconds:
                self.idle_gap_count += 1
        self.last_activity_monotonic = now_monotonic

    def display_seconds(self, now_monotonic: float | None = None):
        if self.last_activity_monotonic is None:
            return self.accumulated_seconds
        if now_monotonic is None:
            now_monotonic = monotonic()
        gap = max(0.0, now_monotonic - self.last_activity_monotonic)
        return self.accumulated_seconds + min(gap, self.idle_timeout_seconds)

    def finish(self, now_monotonic: float):
        self.accumulated_seconds = self.display_seconds(now_monotonic)
        self.last_activity_monotonic = None
        return self.accumulated_seconds


class SessionStore:
    def __init__(self, path=None):
        self.path = Path(path) if path else session_log_path()

    def write(self, payload):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True) + "\n")
        return self.path


class WorkAudit(ScriptedLoadableModule):
    def __init__(self, parent):
        ScriptedLoadableModule.__init__(self, parent)
        self.parent.title = _("WorkAudit")
        self.parent.categories = ["", translate("qSlicerAbstractCoreModule", "Segmentation")]
        self.parent.dependencies = ["Segmentations", "SubjectHierarchy"]
        self.parent.contributors = ["ub", "OpenAI Codex"]
        self.parent.helpText = _(
            """
Transparent, local-only work auditing for segmentation sessions.

What it records:
- case ID entered in this module
- timestamps of segmentation-related Slicer events
- active minutes estimated with an idle timeout

What it does not record:
- screenshots
- webcam or audio
- keystrokes outside Slicer
- image voxels or segmentation pixel data
"""
        )
        self.parent.helpText += parent.defaultDocumentationLink
        self.parent.acknowledgementText = _("Open-source scripted extension.")


class WorkAuditSessionController(VTKObservationMixin):
    def __init__(self):
        VTKObservationMixin.__init__(self)
        self.store = SessionStore()
        self.editor_widget = None
        self.observed_segmentation = None
        self.segmentation_observers = []
        self.session = None
        self.accumulator = None
        self.event_counts = Counter()
        self.events = []
        self.update_callback = None
        self.addObserver(
            slicer.mrmlScene,
            slicer.mrmlScene.EndSaveEvent,
            self._on_scene_saved,
        )

    def set_update_callback(self, callback):
        self.update_callback = callback

    def cleanup(self):
        self.stop_session()
        self._remove_segmentation_observers()
        self._detach_editor()
        self.removeObservers()

    def attach_editor(self):
        editor_widget = slicer.modules.segmenteditor.widgetRepresentation().self()
        if editor_widget is self.editor_widget:
            self._rebind_segmentation_observers()
            return

        self._detach_editor()
        self.editor_widget = editor_widget
        self.editor_widget.editor.connect(
            "segmentationNodeChanged(vtkMRMLSegmentationNode *)",
            self._on_segmentation_node_changed,
        )
        self.editor_widget.editor.connect(
            "currentSegmentIDChanged(QString)",
            self._on_current_segment_changed,
        )
        self.editor_widget.editor.connect(
            "sourceVolumeNodeChanged(vtkMRMLVolumeNode *)",
            self._on_source_volume_changed,
        )
        self._rebind_segmentation_observers()

    def _detach_editor(self):
        if self.editor_widget is None:
            return
        self.editor_widget.editor.disconnect(
            "segmentationNodeChanged(vtkMRMLSegmentationNode *)",
            self._on_segmentation_node_changed,
        )
        self.editor_widget.editor.disconnect(
            "currentSegmentIDChanged(QString)",
            self._on_current_segment_changed,
        )
        self.editor_widget.editor.disconnect(
            "sourceVolumeNodeChanged(vtkMRMLVolumeNode *)",
            self._on_source_volume_changed,
        )
        self.editor_widget = None

    def _current_segmentation(self):
        if self.editor_widget is None:
            return None
        segmentation_node = self.editor_widget.editor.segmentationNode()
        if segmentation_node is None:
            return None
        return segmentation_node.GetSegmentation()

    def _current_segment_id(self):
        if self.editor_widget is None:
            return ""
        return str(self.editor_widget.editor.currentSegmentID())

    def _current_effect_name(self):
        if self.editor_widget is None:
            return ""
        effect = self.editor_widget.editor.activeEffect()
        if effect is None:
            return ""
        return str(effect.name)

    def _segmentation_node_name(self):
        if self.editor_widget is None:
            return ""
        node = self.editor_widget.editor.segmentationNode()
        if node is None:
            return ""
        return node.GetName()

    def _source_volume_name(self):
        if self.editor_widget is None:
            return ""
        node = self.editor_widget.editor.sourceVolumeNode()
        if node is None:
            return ""
        return node.GetName()

    def _resolved_case_id(self, case_id):
        for candidate in (
            case_id.strip(),
            self._source_volume_name(),
            self._segmentation_node_name(),
        ):
            if candidate:
                return candidate
        return "session-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def start_session(self, case_id, worker_id, idle_timeout_seconds):
        if self.session is not None:
            self.stop_session()

        self.attach_editor()

        resolved_case_id = self._resolved_case_id(case_id)
        self.accumulator = ActivityAccumulator(idle_timeout_seconds)
        self.event_counts = Counter()
        self.events = []
        self.session = {
            "schema_version": 1,
            "case_id": resolved_case_id,
            "worker_id": worker_id.strip(),
            "started_at": utcnow_iso(),
            "idle_timeout_seconds": idle_timeout_seconds,
        }

        self._rebind_segmentation_observers()
        self._emit_update()
        return resolved_case_id

    def stop_session(self):
        if self.session is None:
            return None

        stopped_at = utcnow_iso()
        active_seconds = round(self.accumulator.finish(monotonic()), 1)

        payload = {
            "schema_version": self.session["schema_version"],
            "case_id": self.session["case_id"],
            "worker_id": self.session["worker_id"],
            "started_at": self.session["started_at"],
            "stopped_at": stopped_at,
            "idle_timeout_seconds": self.session["idle_timeout_seconds"],
            "active_seconds": active_seconds,
            "active_minutes": round(active_seconds / 60.0, 2),
            "idle_gap_count": self.accumulator.idle_gap_count,
            "event_total": len(self.events),
            "event_counts": dict(self.event_counts),
            "segmentation_node_name": self._segmentation_node_name(),
            "source_volume_name": self._source_volume_name(),
            "events": self.events,
            "slicer": {
                "application_name": slicer.app.applicationName,
                "application_version": slicer.app.applicationVersion,
                "repository_revision": slicer.app.repositoryRevision,
            },
        }

        path = self.store.write(payload)

        self.session = None
        self.accumulator = None
        self.event_counts = Counter()
        self.events = []
        self._emit_update()
        return path

    def state_snapshot(self):
        active = self.session is not None and self.accumulator is not None
        active_seconds = self.accumulator.display_seconds() if active else 0.0
        return {
            "active": active,
            "case_id": self.session["case_id"] if active else "",
            "worker_id": self.session["worker_id"] if active else "",
            "active_seconds": active_seconds,
            "active_minutes": active_seconds / 60.0,
            "idle_gap_count": self.accumulator.idle_gap_count if active else 0,
            "event_total": len(self.events),
            "log_path": str(self.store.path),
        }

    def _emit_update(self):
        if self.update_callback is not None:
            self.update_callback()

    def _append_event(self, event_type, extra=None):
        if self.session is None or self.accumulator is None:
            return

        self.accumulator.note_activity(monotonic())

        payload = {
            "ts": utcnow_iso(),
            "type": event_type,
            "effect": self._current_effect_name(),
            "segment_id": self._current_segment_id(),
            "segmentation_node_name": self._segmentation_node_name(),
            "source_volume_name": self._source_volume_name(),
        }
        if extra is not None:
            payload.update(extra)

        self.events.append(payload)
        self.event_counts[event_type] += 1
        self._emit_update()

    def _rebind_segmentation_observers(self):
        segmentation = self._current_segmentation()
        if segmentation is self.observed_segmentation:
            return

        self._remove_segmentation_observers()
        self.observed_segmentation = segmentation
        if segmentation is None:
            return

        event_map = (
            (vtkSegmentationCore.vtkSegmentation.SourceRepresentationModified, "source_representation_modified"),
            (vtkSegmentationCore.vtkSegmentation.SegmentModified, "segment_modified"),
            (vtkSegmentationCore.vtkSegmentation.RepresentationModified, "representation_modified"),
            (vtkSegmentationCore.vtkSegmentation.SegmentAdded, "segment_added"),
            (vtkSegmentationCore.vtkSegmentation.SegmentRemoved, "segment_removed"),
            (vtkSegmentationCore.vtkSegmentation.SegmentsOrderModified, "segments_order_modified"),
        )

        for event_id, event_name in event_map:
            callback = lambda caller, event, name=event_name: self._on_segmentation_activity(name)
            tag = segmentation.AddObserver(event_id, callback)
            self.segmentation_observers.append((tag, callback))

    def _remove_segmentation_observers(self):
        if self.observed_segmentation is None:
            return
        while self.segmentation_observers:
            tag, _callback = self.segmentation_observers.pop()
            self.observed_segmentation.RemoveObserver(tag)
        self.observed_segmentation = None

    def _on_segmentation_activity(self, event_name):
        self._append_event(event_name)

    def _on_segmentation_node_changed(self, node):
        self._rebind_segmentation_observers()
        node_name = node.GetName() if node is not None else ""
        self._append_event("segmentation_node_changed", {"segmentation_node_name": node_name})

    def _on_current_segment_changed(self, segment_id):
        self._append_event("current_segment_changed", {"segment_id": str(segment_id)})

    def _on_source_volume_changed(self, node):
        node_name = node.GetName() if node is not None else ""
        self._append_event("source_volume_changed", {"source_volume_name": node_name})

    def _on_scene_saved(self, caller=None, event=None):
        self._append_event("scene_saved")


class WorkAuditWidget(ScriptedLoadableModuleWidget):
    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        self.controller = None
        self.timer = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        self.controller = WorkAuditSessionController()
        self.controller.set_update_callback(self.update_status)

        self.notice_label = qt.QLabel(
            "Open-source local audit only. No screenshots, no audio/video, no off-app monitoring, and no voxel data are recorded."
        )
        self.notice_label.wordWrap = True
        self.layout.addWidget(self.notice_label)

        self.form_layout = qt.QFormLayout()

        self.case_id_edit = qt.QLineEdit()
        self.case_id_edit.setPlaceholderText("Case ID or leave blank to infer from current nodes")
        self.form_layout.addRow("Case ID", self.case_id_edit)

        self.worker_id_edit = qt.QLineEdit()
        self.worker_id_edit.setPlaceholderText("Optional worker or vendor identifier")
        self.form_layout.addRow("Worker ID", self.worker_id_edit)

        self.idle_timeout_spin = qt.QSpinBox()
        self.idle_timeout_spin.setRange(30, 600)
        self.idle_timeout_spin.setSingleStep(15)
        self.form_layout.addRow("Idle timeout (s)", self.idle_timeout_spin)

        self.layout.addLayout(self.form_layout)

        self.button_row = qt.QHBoxLayout()

        self.start_button = qt.QPushButton("Start session")
        self.start_button.clicked.connect(self.on_start_clicked)
        self.button_row.addWidget(self.start_button)

        self.stop_button = qt.QPushButton("Stop session")
        self.stop_button.clicked.connect(self.on_stop_clicked)
        self.button_row.addWidget(self.stop_button)

        self.open_log_dir_button = qt.QPushButton("Open log directory")
        self.open_log_dir_button.clicked.connect(self.open_log_directory)
        self.button_row.addWidget(self.open_log_dir_button)

        self.layout.addLayout(self.button_row)

        self.status_layout = qt.QFormLayout()

        self.status_value = qt.QLabel("")
        self.status_layout.addRow("Status", self.status_value)

        self.active_minutes_value = qt.QLabel("")
        self.status_layout.addRow("Active minutes", self.active_minutes_value)

        self.event_total_value = qt.QLabel("")
        self.status_layout.addRow("Event count", self.event_total_value)

        self.log_path_value = qt.QLabel("")
        self.log_path_value.wordWrap = True
        self.status_layout.addRow("Log path", self.log_path_value)

        self.layout.addLayout(self.status_layout)
        self.layout.addStretch(1)

        self._load_defaults()

        self.timer = qt.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_status)
        self.timer.start()

        self.update_status()

    def enter(self):
        self.controller.attach_editor()
        self.update_status()

    def cleanup(self):
        if self.timer is not None:
            self.timer.stop()
        if self.controller is not None:
            self.controller.cleanup()

    def _settings(self):
        return slicer.app.settings()

    def _load_defaults(self):
        settings = self._settings()
        self.case_id_edit.text = settings.value(f"{SETTINGS_ROOT}/lastCaseId", "")
        self.worker_id_edit.text = settings.value(f"{SETTINGS_ROOT}/lastWorkerId", "")
        idle_timeout = int(settings.value(f"{SETTINGS_ROOT}/idleTimeoutSeconds", DEFAULT_IDLE_TIMEOUT_SECONDS))
        self.idle_timeout_spin.value = idle_timeout

    def _save_defaults(self):
        settings = self._settings()
        settings.setValue(f"{SETTINGS_ROOT}/lastCaseId", self.case_id_edit.text)
        settings.setValue(f"{SETTINGS_ROOT}/lastWorkerId", self.worker_id_edit.text)
        settings.setValue(f"{SETTINGS_ROOT}/idleTimeoutSeconds", self.idle_timeout_spin.value)

    def on_start_clicked(self):
        resolved_case_id = self.controller.start_session(
            self.case_id_edit.text,
            self.worker_id_edit.text,
            self.idle_timeout_spin.value,
        )
        self.case_id_edit.text = resolved_case_id
        self._save_defaults()
        self.update_status()

    def on_stop_clicked(self):
        path = self.controller.stop_session()
        self.update_status()
        if path is not None:
            slicer.util.infoDisplay(f"WorkAudit wrote session log to:\n{path}")

    def open_log_directory(self):
        log_dir = workaudit_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        qt.QDesktopServices.openUrl(qt.QUrl.fromLocalFile(str(log_dir)))

    def update_status(self):
        snapshot = self.controller.state_snapshot()

        if snapshot["active"]:
            self.status_value.text = f"Running ({snapshot['case_id']})"
        else:
            self.status_value.text = "Idle"

        self.active_minutes_value.text = f"{snapshot['active_minutes']:.2f}"
        self.event_total_value.text = f"{snapshot['event_total']} events, {snapshot['idle_gap_count']} idle gaps"
        self.log_path_value.text = snapshot["log_path"]

        self.start_button.enabled = not snapshot["active"]
        self.stop_button.enabled = snapshot["active"]


class WorkAuditTest(ScriptedLoadableModuleTest):
    def setUp(self):
        slicer.mrmlScene.Clear(0)

    def runTest(self):
        self.setUp()
        self.test_WorkAuditAccumulator()

    def test_WorkAuditAccumulator(self):
        accumulator = ActivityAccumulator(idle_timeout_seconds=90)
        accumulator.note_activity(0.0)
        accumulator.note_activity(30.0)
        self.assertEqual(round(accumulator.display_seconds(45.0), 1), 45.0)

        accumulator.note_activity(200.0)
        self.assertEqual(accumulator.idle_gap_count, 1)
        self.assertEqual(round(accumulator.display_seconds(230.0), 1), 150.0)

        accumulator.finish(230.0)
        self.assertEqual(round(accumulator.accumulated_seconds, 1), 150.0)
        self.delayDisplay("WorkAudit accumulator test passed")
