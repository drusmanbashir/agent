from pathlib import Path
import json
import os

import qt


REGISTRY_PATH = Path.home() / ".config" / "slicer.org" / "file_dialog_favorites.json"


class SidebarRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.save_paths([])

    def normalize_path(self, path):
        return os.path.normpath(os.path.abspath(os.path.expanduser(path)))

    def load_paths(self):
        data = json.loads(self.path.read_text())
        paths = []
        seen = set()
        for path in data["paths"]:
            normalized = self.normalize_path(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            paths.append(normalized)
        return paths

    def save_paths(self, paths):
        normalized_paths = []
        seen = set()
        for path in paths:
            normalized = self.normalize_path(path)
            if normalized in seen:
                continue
            seen.add(normalized)
            normalized_paths.append(normalized)
        payload = {"paths": normalized_paths}
        self.path.write_text(json.dumps(payload, indent=2) + "\n")

    def paths_from_urls(self, urls):
        paths = []
        seen = set()
        for url in urls:
            if not url.isLocalFile():
                continue
            path = self.normalize_path(url.toLocalFile())
            if path in seen:
                continue
            seen.add(path)
            paths.append(path)
        return paths

    def urls_from_paths(self, paths):
        return [qt.QUrl.fromLocalFile(path) for path in paths]


class FileDialogFavoritesShim(qt.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.registry = SidebarRegistry(REGISTRY_PATH)
        self.baselines = {}
        qt.QApplication.instance().installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() != qt.QEvent.Show:
            return False
        if not watched.inherits("QFileDialog"):
            return False
        dialog_id = id(watched)
        if dialog_id in self.baselines:
            return False
        baseline_urls = list(watched.sidebarUrls())
        self.baselines[dialog_id] = baseline_urls
        watched.setSidebarUrls(self.merged_urls(baseline_urls))
        watched.finished.connect(lambda result, dialog=watched: self.persist_dialog(dialog))
        watched.destroyed.connect(lambda obj=None, dialog_id=dialog_id: self.drop_dialog(dialog_id))
        return False

    def merged_urls(self, baseline_urls):
        baseline_paths = self.registry.paths_from_urls(baseline_urls)
        merged_paths = list(baseline_paths)
        for path in self.registry.load_paths():
            if path not in merged_paths:
                merged_paths.append(path)
        return self.registry.urls_from_paths(merged_paths)

    def persist_dialog(self, dialog):
        dialog_id = id(dialog)
        baseline_paths = self.registry.paths_from_urls(self.baselines[dialog_id])
        current_paths = self.registry.paths_from_urls(dialog.sidebarUrls())
        custom_paths = []
        for path in current_paths:
            if path not in baseline_paths:
                custom_paths.append(path)
        self.registry.save_paths(custom_paths)

    def drop_dialog(self, dialog_id):
        if dialog_id in self.baselines:
            del self.baselines[dialog_id]


_slicer_file_dialog_favorites_shim = FileDialogFavoritesShim()
