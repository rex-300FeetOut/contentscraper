# pyright: reportMissingImports=false
import sys
from typing import List, Optional
from contextlib import redirect_stderr, redirect_stdout

from PySide6.QtCore import QObject, QThread, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import scraper


class SignalTextWriter:
    def __init__(self, emit_func):
        self.emit_func = emit_func
        self._buffer = ""

    def write(self, text):
        if not text:
            return 0
        self._buffer += text
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.emit_func(line)
        return len(text)

    def flush(self):
        if self._buffer.strip():
            self.emit_func(self._buffer.strip())
        self._buffer = ""


class ScrapeWorker(QObject):
    log = Signal(str)
    done = Signal(bool, str)

    def __init__(
        self,
        sitemap_input: str,
        output_dir: str,
        max_pages: int,
        delay_seconds: float,
        main_content_only: bool,
        main_selector: Optional[str],
        output_format: str,
        combine_per_domain: bool,
        selected_sub_sitemaps: List[str],
        render_mode: str,
        fallback_min_chars: int,
    ):
        super().__init__()
        self.sitemap_input = sitemap_input
        self.output_dir = output_dir
        self.max_pages = max_pages
        self.delay_seconds = delay_seconds
        self.main_content_only = main_content_only
        self.main_selector = main_selector
        self.output_format = output_format
        self.combine_per_domain = combine_per_domain
        self.selected_sub_sitemaps = selected_sub_sitemaps
        self.render_mode = render_mode
        self.fallback_min_chars = fallback_min_chars

    @Slot()
    def run(self):
        try:
            text_writer = SignalTextWriter(self.log.emit)
            with redirect_stdout(text_writer), redirect_stderr(text_writer):
                sitemap_url = scraper.normalize_input_to_sitemap(self.sitemap_input)
                self.log.emit(f"Using sitemap URL: {sitemap_url}")

                urls_override = None
                if self.selected_sub_sitemaps:
                    all_urls = []
                    for sub in self.selected_sub_sitemaps:
                        self.log.emit(f"Loading URLs from sub-sitemap: {sub}")
                        all_urls.extend(scraper.get_sitemap_urls(sub))
                    urls_override = list(dict.fromkeys(all_urls))
                    self.log.emit(
                        f"Collected {len(urls_override)} URL(s) from selected sub-sitemaps."
                    )

                scraper.main(
                    sitemap_url=sitemap_url,
                    output_dir=self.output_dir,
                    max_saved_pages=self.max_pages,
                    request_delay_seconds=self.delay_seconds,
                    main_content_only=self.main_content_only,
                    output_format=self.output_format,
                    combine_per_domain=self.combine_per_domain,
                    urls_override=urls_override,
                    main_content_selector=self.main_selector,
                    render_mode=self.render_mode,
                    browser_fallback_min_text_chars=self.fallback_min_chars,
                )
                text_writer.flush()
            self.done.emit(True, "Scrape run completed.")
        except Exception as e:
            self.done.emit(False, f"Scrape failed: {e}")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Content Scraper MVP")
        self.resize(950, 700)

        self.worker_thread: Optional[QThread] = None
        self.worker: Optional[ScrapeWorker] = None

        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        main_layout = QVBoxLayout(root)

        form_group = QGroupBox("Scrape Settings")
        form_layout = QFormLayout(form_group)

        self.sitemap_input = QLineEdit()
        self.sitemap_input.setPlaceholderText("example.com or https://example.com/sitemap.xml")
        form_layout.addRow("Sitemap/Domain:", self.sitemap_input)

        sub_layout = QHBoxLayout()
        self.load_subs_button = QPushButton("Load Sub-sitemaps")
        self.load_subs_button.clicked.connect(self.load_sub_sitemaps)
        sub_layout.addWidget(self.load_subs_button)
        sub_layout.addWidget(QLabel("Select one or more (if available):"))
        form_layout.addRow(sub_layout)

        self.sub_sitemaps_list = QListWidget()
        self.sub_sitemaps_list.setSelectionMode(QListWidget.MultiSelection)
        self.sub_sitemaps_list.setMinimumHeight(120)
        # Give sub-sitemap chooser more room for long URLs.
        self.sub_sitemaps_list.setMinimumWidth(600)
        form_layout.addRow("Sub-sitemaps:", self.sub_sitemaps_list)

        output_layout = QHBoxLayout()
        self.output_dir_input = QLineEdit("scraped_pages")
        output_layout.addWidget(self.output_dir_input, 1)
        self.output_browse_button = QPushButton("Choose...")
        self.output_browse_button.clicked.connect(self.choose_output_dir)
        output_layout.addWidget(self.output_browse_button)
        form_layout.addRow("Output folder:", output_layout)

        self.max_pages_input = QSpinBox()
        self.max_pages_input.setRange(0, 1_000_000)
        self.max_pages_input.setValue(10)
        form_layout.addRow("Max pages (0=unlimited):", self.max_pages_input)

        self.delay_input = QDoubleSpinBox()
        self.delay_input.setRange(0.0, 60.0)
        self.delay_input.setSingleStep(0.1)
        self.delay_input.setValue(1.0)
        form_layout.addRow("Delay seconds:", self.delay_input)

        self.main_only_checkbox = QCheckBox("Main content only")
        self.main_only_checkbox.setChecked(False)
        form_layout.addRow(self.main_only_checkbox)

        self.main_selector_input = QLineEdit()
        self.main_selector_input.setPlaceholderText("Optional CSS selector (e.g. .entry-content)")
        form_layout.addRow("Main selector:", self.main_selector_input)

        self.format_input = QComboBox()
        self.format_input.addItems(["rtf", "docx"])
        form_layout.addRow("Output format:", self.format_input)

        self.render_mode_input = QComboBox()
        self.render_mode_input.addItems(["auto", "requests", "browser"])
        self.render_mode_input.setCurrentText("auto")
        form_layout.addRow("Render mode:", self.render_mode_input)

        self.fallback_chars_input = QSpinBox()
        self.fallback_chars_input.setRange(0, 200000)
        self.fallback_chars_input.setValue(300)
        form_layout.addRow("Auto fallback min chars:", self.fallback_chars_input)

        self.combine_checkbox = QCheckBox("Combine all pages into one document per domain")
        self.combine_checkbox.setChecked(False)
        form_layout.addRow(self.combine_checkbox)

        main_layout.addWidget(form_group)

        action_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Scrape")
        self.start_button.clicked.connect(self.start_scrape)
        action_layout.addWidget(self.start_button)

        self.clear_log_button = QPushButton("Clear Log")
        self.clear_log_button.clicked.connect(self.clear_log)
        action_layout.addWidget(self.clear_log_button)
        action_layout.addStretch(1)
        main_layout.addLayout(action_layout)

        self.log_output = QTextEdit()
        self.log_output.setReadOnly(True)
        main_layout.addWidget(self.log_output)

    def append_log(self, text: str):
        self.log_output.append(text)

    @Slot()
    def clear_log(self):
        self.log_output.clear()

    @Slot()
    def load_sub_sitemaps(self):
        sitemap_text = self.sitemap_input.text().strip()
        if not sitemap_text:
            QMessageBox.warning(self, "Missing input", "Enter a sitemap/domain first.")
            return
        try:
            sitemap_url = scraper.normalize_input_to_sitemap(sitemap_text)
            sub_sitemaps = scraper.get_direct_sub_sitemaps(sitemap_url)
            self.sub_sitemaps_list.clear()
            if not sub_sitemaps:
                self.append_log("No sitemap index detected (or no child sub-sitemaps found).")
                return
            for sub in sub_sitemaps:
                item = QListWidgetItem(sub)
                self.sub_sitemaps_list.addItem(item)
                item.setSelected(True)
            self.append_log(f"Loaded {len(sub_sitemaps)} sub-sitemap(s).")
        except Exception as e:
            QMessageBox.critical(self, "Error loading sub-sitemaps", str(e))

    @Slot()
    def choose_output_dir(self):
        current_value = self.output_dir_input.text().strip() or "scraped_pages"
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            "Choose Output Folder",
            current_value,
        )
        if selected_dir:
            self.output_dir_input.setText(selected_dir)

    @Slot()
    def start_scrape(self):
        if self.worker_thread is not None:
            QMessageBox.information(self, "Already running", "A scrape is already in progress.")
            return

        sitemap_text = self.sitemap_input.text().strip()
        if not sitemap_text:
            QMessageBox.warning(self, "Missing input", "Please enter a sitemap/domain.")
            return

        selected_sub_sitemaps = [item.text() for item in self.sub_sitemaps_list.selectedItems()]

        selector_text = self.main_selector_input.text().strip()
        selector_value = selector_text if selector_text else None

        self.worker = ScrapeWorker(
            sitemap_input=sitemap_text,
            output_dir=self.output_dir_input.text().strip() or "scraped_pages",
            max_pages=self.max_pages_input.value(),
            delay_seconds=float(self.delay_input.value()),
            main_content_only=self.main_only_checkbox.isChecked(),
            main_selector=selector_value,
            output_format=self.format_input.currentText(),
            combine_per_domain=self.combine_checkbox.isChecked(),
            selected_sub_sitemaps=selected_sub_sitemaps,
            render_mode=self.render_mode_input.currentText(),
            fallback_min_chars=self.fallback_chars_input.value(),
        )
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.done.connect(self.on_scrape_done)
        self.worker.log.connect(self.append_log)
        self.worker.done.connect(lambda *_: self.worker_thread.quit())
        self.worker_thread.finished.connect(self.cleanup_worker)

        self.start_button.setEnabled(False)
        self.append_log("Starting scrape...")
        self.worker_thread.start()

    @Slot(bool, str)
    def on_scrape_done(self, success: bool, message: str):
        if success:
            self.append_log(message)
        else:
            self.append_log(message)
            QMessageBox.critical(self, "Scrape error", message)

    @Slot()
    def cleanup_worker(self):
        self.start_button.setEnabled(True)
        if self.worker is not None:
            self.worker.deleteLater()
        if self.worker_thread is not None:
            self.worker_thread.deleteLater()
        self.worker = None
        self.worker_thread = None


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
