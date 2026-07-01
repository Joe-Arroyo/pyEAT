"""
Chronopotentiometry analysis tab
Multi-file overlay with EIS-style file list, time units, scale controls, skip, scatter
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QGroupBox, QComboBox, QLineEdit, QCheckBox, QRadioButton,
    QListWidget, QListWidgetItem, QScrollArea, QDialog, QFormLayout,
    QDialogButtonBox, QSpinBox
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import numpy as np

from parsers.gamry import load_gamry_file
from parsers.autolab import (
    load_autolab_chronopotentiometry_ascii,
    load_autolab_chronopotentiometry_excel,
)
from parsers.riden import load_riden_file
from parsers.custom_csv import load_custom_csv


# Maps combo index to (label, file_filter, multi_select)
INSTRUMENTS = [
    ("Gamry (.DTA)",           "DTA Files (*.DTA);;All Files (*)"),
    ("Autolab ASCII (.txt)",   "Text Files (*.txt);;All Files (*)"),
    ("Autolab Excel (.xlsx)",  "Excel Files (*.xlsx);;All Files (*)"),
    ("Riden RD6006 (.xlsx)",   "Excel Files (*.xlsx);;All Files (*)"),
    ("Custom CSV (.csv)",      "CSV Files (*.csv);;All Files (*)"),
]

TIME_DIVISORS = {"Seconds": 1.0, "Minutes": 60.0, "Hours": 3600.0}
TIME_LABELS   = {"Seconds": "Time (s)", "Minutes": "Time (min)", "Hours": "Time (h)"}


class ChronopotentiometryTab(QWidget):
    """Tab for chronopotentiometry analysis — multi-file overlay"""

    def __init__(self):
        super().__init__()
        self.loaded_files  = {}   # filename -> ElectrolyzerData
        self.display_names = {}   # filename -> legend label
        self.colors = plt.cm.tab10(np.linspace(0, 1, 10))
        self.init_ui()

    # ── UI ────────────────────────────────────────────────────────────

    def init_ui(self):
        main_layout = QHBoxLayout(self)

        # Scrollable left panel
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setMaximumWidth(500)
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_scroll.setWidget(left_panel)

        # ── File loading ───────────────────────────────────────────────
        file_group = QGroupBox("📁 Load Data")
        file_layout = QVBoxLayout()

        file_layout.addWidget(QLabel("Instrument:"))
        self.instrument_combo = QComboBox()
        self.instrument_combo.addItems([label for label, _ in INSTRUMENTS])
        file_layout.addWidget(self.instrument_combo)

        self.load_btn = QPushButton("Load File(s)")
        self.load_btn.clicked.connect(self.load_files)
        self.load_btn.setMinimumHeight(40)
        file_layout.addWidget(self.load_btn)

        file_layout.addWidget(QLabel("Loaded Files: (drag to reorder, double-click to rename)"))
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(160)
        self.file_list.setDragDropMode(QListWidget.InternalMove)
        self.file_list.itemChanged.connect(self.update_plot)
        self.file_list.itemDoubleClicked.connect(self.rename_file_item)
        file_layout.addWidget(self.file_list)

        list_btn_row = QHBoxLayout()
        self.remove_btn = QPushButton("Remove Selected")
        self.remove_btn.clicked.connect(self.remove_selected_files)
        list_btn_row.addWidget(self.remove_btn)
        self.clear_btn = QPushButton("Clear All")
        self.clear_btn.clicked.connect(self.clear_all_files)
        list_btn_row.addWidget(self.clear_btn)
        file_layout.addLayout(list_btn_row)

        self.status_label = QLabel("No files loaded")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            "padding: 8px; background-color: #f0f0f0; border-radius: 5px;"
        )
        file_layout.addWidget(self.status_label)

        file_group.setLayout(file_layout)
        left_layout.addWidget(file_group)

        # ── Plot selection ─────────────────────────────────────────────
        plot_group = QGroupBox("📊 Plot Selection")
        plot_layout = QVBoxLayout()

        self.plot_voltage_radio = QRadioButton("Voltage vs Time")
        self.plot_current_radio = QRadioButton("Current vs Time")
        self.plot_both_radio    = QRadioButton("Both (2 subplots)")
        self.plot_both_radio.setChecked(True)

        for rb in (self.plot_voltage_radio, self.plot_current_radio, self.plot_both_radio):
            rb.toggled.connect(self.update_plot)
            plot_layout.addWidget(rb)

        plot_group.setLayout(plot_layout)
        left_layout.addWidget(plot_group)

        # ── Time units ─────────────────────────────────────────────────
        units_group = QGroupBox("⏱️ Time Units")
        units_layout = QVBoxLayout()

        self.units_seconds = QRadioButton("Seconds")
        self.units_minutes = QRadioButton("Minutes")
        self.units_hours   = QRadioButton("Hours")
        self.units_seconds.setChecked(True)

        for rb in (self.units_seconds, self.units_minutes, self.units_hours):
            rb.toggled.connect(self.on_unit_changed)
            units_layout.addWidget(rb)

        units_group.setLayout(units_layout)
        left_layout.addWidget(units_group)

        # ── X scale ────────────────────────────────────────────────────
        xscale_group = QGroupBox("↔️ X-Axis Limits")
        xscale_layout = QVBoxLayout()

        self.enable_xscale = QCheckBox("Enable X-axis limits")
        self.enable_xscale.stateChanged.connect(self.toggle_xscale)
        xscale_layout.addWidget(self.enable_xscale)

        row = QHBoxLayout()
        row.addWidget(QLabel("Min:"))
        self.time_min = QLineEdit()
        self.time_min.setPlaceholderText("auto")
        self.time_min.setEnabled(False)
        self.time_min.textChanged.connect(self.update_plot)
        row.addWidget(self.time_min)
        row.addWidget(QLabel("Max:"))
        self.time_max = QLineEdit()
        self.time_max.setPlaceholderText("auto")
        self.time_max.setEnabled(False)
        self.time_max.textChanged.connect(self.update_plot)
        row.addWidget(self.time_max)
        xscale_layout.addLayout(row)

        xscale_group.setLayout(xscale_layout)
        left_layout.addWidget(xscale_group)

        # ── Y scale ────────────────────────────────────────────────────
        yscale_group = QGroupBox("↕️ Y-Axis Limits")
        yscale_layout = QVBoxLayout()

        self.enable_yscale = QCheckBox("Enable Y-axis limits")
        self.enable_yscale.stateChanged.connect(self.toggle_yscale)
        yscale_layout.addWidget(self.enable_yscale)

        # Voltage limits
        yscale_layout.addWidget(QLabel("Voltage (V):"))
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Min:"))
        self.vmin_input = QLineEdit()
        self.vmin_input.setPlaceholderText("auto")
        self.vmin_input.setEnabled(False)
        self.vmin_input.textChanged.connect(self.update_plot)
        vrow.addWidget(self.vmin_input)
        vrow.addWidget(QLabel("Max:"))
        self.vmax_input = QLineEdit()
        self.vmax_input.setPlaceholderText("auto")
        self.vmax_input.setEnabled(False)
        self.vmax_input.textChanged.connect(self.update_plot)
        vrow.addWidget(self.vmax_input)
        yscale_layout.addLayout(vrow)

        # Current limits
        yscale_layout.addWidget(QLabel("Current (A):"))
        irow = QHBoxLayout()
        irow.addWidget(QLabel("Min:"))
        self.imin_input = QLineEdit()
        self.imin_input.setPlaceholderText("auto")
        self.imin_input.setEnabled(False)
        self.imin_input.textChanged.connect(self.update_plot)
        irow.addWidget(self.imin_input)
        irow.addWidget(QLabel("Max:"))
        self.imax_input = QLineEdit()
        self.imax_input.setPlaceholderText("auto")
        self.imax_input.setEnabled(False)
        self.imax_input.textChanged.connect(self.update_plot)
        irow.addWidget(self.imax_input)
        yscale_layout.addLayout(irow)

        yscale_group.setLayout(yscale_layout)
        left_layout.addWidget(yscale_group)

        # ── Skip data points ───────────────────────────────────────────
        skip_group = QGroupBox("⏩ Data Points")
        skip_layout = QHBoxLayout()
        skip_layout.addWidget(QLabel("Plot every Nth point:"))
        self.skip_input = QSpinBox()
        self.skip_input.setMinimum(1)
        self.skip_input.setMaximum(1000)
        self.skip_input.setValue(1)
        self.skip_input.valueChanged.connect(self.update_plot)
        skip_layout.addWidget(self.skip_input)
        skip_group.setLayout(skip_layout)
        left_layout.addWidget(skip_group)

        # ── Export ─────────────────────────────────────────────────────
        export_group = QGroupBox("💾 Export")
        export_layout = QVBoxLayout()

        self.export_csv_btn = QPushButton("Save as CSV")
        self.export_csv_btn.clicked.connect(self.export_csv)
        self.export_csv_btn.setEnabled(False)
        export_layout.addWidget(self.export_csv_btn)

        self.export_png_btn = QPushButton("Save Plot as PNG")
        self.export_png_btn.clicked.connect(self.export_png)
        self.export_png_btn.setEnabled(False)
        export_layout.addWidget(self.export_png_btn)

        export_group.setLayout(export_layout)
        left_layout.addWidget(export_group)

        left_layout.addStretch()

        # ── Right panel ────────────────────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.figure = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas)

        main_layout.addWidget(left_scroll)
        main_layout.addWidget(right_panel)

        self.show_empty_plot()

    # ── Helpers ───────────────────────────────────────────────────────

    def show_empty_plot(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(
            0.5, 0.5,
            "Load chronopotentiometry file(s) to display data",
            ha="center", va="center", fontsize=14, color="gray",
        )
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw()

    def _get_time_divisor(self):
        for rb, key in (
            (self.units_seconds, "Seconds"),
            (self.units_minutes, "Minutes"),
            (self.units_hours,   "Hours"),
        ):
            if rb.isChecked():
                return TIME_DIVISORS[key], TIME_LABELS[key]
        return 1.0, "Time (s)"

    def toggle_xscale(self, state):
        enabled = state == Qt.Checked
        self.time_min.setEnabled(enabled)
        self.time_max.setEnabled(enabled)

    def toggle_yscale(self, state):
        enabled = state == Qt.Checked
        for w in (self.vmin_input, self.vmax_input, self.imin_input, self.imax_input):
            w.setEnabled(enabled)

    def on_unit_changed(self):
        self.update_plot()

    def _update_status(self):
        n = len(self.loaded_files)
        if n == 0:
            self.status_label.setText("No files loaded")
        elif n == 1:
            self.status_label.setText("✓ 1 file loaded")
        else:
            self.status_label.setText(f"✓ {n} files loaded")

    def _set_export_enabled(self, enabled: bool):
        self.export_csv_btn.setEnabled(enabled)
        self.export_png_btn.setEnabled(enabled)

    # ── File list interaction ─────────────────────────────────────────

    def rename_file_item(self, item):
        """Double-click a list item to rename its legend label."""
        filename = item.data(Qt.UserRole)
        current_name = self.display_names.get(filename, filename)

        dialog = QDialog(self)
        dialog.setWindowTitle("Rename Legend Label")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Legend label:"))
        line_edit = QLineEdit(current_name)
        layout.addWidget(line_edit)
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dialog.accept)
        btn_box.rejected.connect(dialog.reject)
        layout.addWidget(btn_box)

        if dialog.exec_():
            new_name = line_edit.text().strip() or current_name
            self.display_names[filename] = new_name
            item.setText(new_name)
            self.update_plot()

    def remove_selected_files(self):
        for item in self.file_list.selectedItems():
            filename = item.data(Qt.UserRole)
            self.loaded_files.pop(filename, None)
            self.display_names.pop(filename, None)
            self.file_list.takeItem(self.file_list.row(item))

        self._update_status()
        if not self.loaded_files:
            self.show_empty_plot()
            self._set_export_enabled(False)
        else:
            self.update_plot()

    def clear_all_files(self):
        self.loaded_files.clear()
        self.display_names.clear()
        self.file_list.clear()
        self._update_status()
        self.show_empty_plot()
        self._set_export_enabled(False)

    # ── Loading ───────────────────────────────────────────────────────

    def load_files(self):
        idx = self.instrument_combo.currentIndex()
        _, file_filter = INSTRUMENTS[idx]

        file_paths, _ = QFileDialog.getOpenFileNames(
            self, "Select File(s)", "", file_filter
        )
        for fp in file_paths:
            self._load_single(idx, fp)

    def _load_single(self, instrument_idx: int, file_path: str):
        try:
            data = self._parse_file(instrument_idx, file_path)
        except Exception as e:
            self.status_label.setText(f"❌ Error: {e}")
            return

        if data is None:
            self.status_label.setText("❌ Failed to load — check the console")
            return

        filename = data.source_file.name
        # Avoid duplicate entries in the list
        if filename in self.loaded_files:
            self.status_label.setText(f"ℹ️ Already loaded: {filename}")
            return

        self.loaded_files[filename] = data
        # Strip common extensions for the default legend label
        display = filename
        for ext in (".DTA", ".txt", ".xlsx", ".xls", ".csv"):
            display = display.replace(ext, "")
        self.display_names[filename] = display

        item = QListWidgetItem(display)
        item.setData(Qt.UserRole, filename)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.file_list.addItem(item)

        self._update_status()
        self._set_export_enabled(True)
        self.update_plot()

    def _parse_file(self, instrument_idx: int, file_path: str):
        if instrument_idx == 0:
            return load_gamry_file(file_path, technique="chronopotentiometry")
        elif instrument_idx == 1:
            return load_autolab_chronopotentiometry_ascii(file_path)
        elif instrument_idx == 2:
            return load_autolab_chronopotentiometry_excel(file_path)
        elif instrument_idx == 3:
            return load_riden_file(file_path, technique="chronopotentiometry")
        elif instrument_idx == 4:
            return load_custom_csv(file_path)
        return None

    # ── Data ──────────────────────────────────────────────────────────

    def _get_file_data(self, filename):
        """Return (t, voltage, current) arrays for one file, with skip applied."""
        data = self.loaded_files[filename]
        skip = self.skip_input.value()
        divisor, _ = self._get_time_divisor()

        t       = data.time[::skip].values    / divisor
        voltage = data.voltage[::skip].values
        current = data.current[::skip].values
        return t, voltage, current

    # ── Plotting ──────────────────────────────────────────────────────

    def update_plot(self):
        if not self.loaded_files:
            return
        self.plot_chronopotentiometry()

    def plot_chronopotentiometry(self):
        _, time_label = self._get_time_divisor()

        # Collect checked files in list order
        checked = []
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            if item.checkState() == Qt.Checked:
                filename = item.data(Qt.UserRole)
                if filename in self.loaded_files:
                    checked.append(filename)

        if not checked:
            self.show_empty_plot()
            return

        self.figure.clear()

        show_voltage = self.plot_voltage_radio.isChecked() or self.plot_both_radio.isChecked()
        show_current = self.plot_current_radio.isChecked() or self.plot_both_radio.isChecked()
        show_both    = self.plot_both_radio.isChecked()

        if show_both:
            ax_v = self.figure.add_subplot(211)
            ax_i = self.figure.add_subplot(212)
        elif show_voltage:
            ax_v = self.figure.add_subplot(111)
            ax_i = None
        else:
            ax_v = None
            ax_i = self.figure.add_subplot(111)

        for idx, filename in enumerate(checked):
            color = self.colors[idx % len(self.colors)]
            label = self.display_names[filename]
            t, voltage, current = self._get_file_data(filename)

            if ax_v is not None:
                ax_v.scatter(t, voltage, s=5, color=color, label=label)
            if ax_i is not None:
                ax_i.scatter(t, current, s=5, color=color, label=label)

        # Format voltage axis
        if ax_v is not None:
            ax_v.set_ylabel("Voltage (V)", fontsize=11)
            ax_v.set_title("Voltage vs Time", fontsize=12, fontweight="bold")
            ax_v.grid(True, alpha=0.3)
            if show_both:
                ax_v.tick_params(labelbottom=False)
            else:
                ax_v.set_xlabel(time_label, fontsize=11)
            if len(checked) > 1:
                ax_v.legend(fontsize=9, loc="best")

        # Format current axis
        if ax_i is not None:
            ax_i.set_xlabel(time_label, fontsize=11)
            ax_i.set_ylabel("Current (A)", fontsize=11)
            ax_i.set_title("Current vs Time", fontsize=12, fontweight="bold")
            ax_i.grid(True, alpha=0.3)
            if ax_v is None and len(checked) > 1:
                ax_i.legend(fontsize=9, loc="best")

        # Apply axis limits after plotting
        for ax in self.figure.get_axes():
            title = ax.get_title()
            try:
                if self.enable_xscale.isChecked():
                    xmin = float(self.time_min.text()) if self.time_min.text() else None
                    xmax = float(self.time_max.text()) if self.time_max.text() else None
                    ax.set_xlim(xmin, xmax)
                if self.enable_yscale.isChecked():
                    if "Voltage" in title:
                        vmin = float(self.vmin_input.text()) if self.vmin_input.text() else None
                        vmax = float(self.vmax_input.text()) if self.vmax_input.text() else None
                        ax.set_ylim(vmin, vmax)
                    elif "Current" in title:
                        imin = float(self.imin_input.text()) if self.imin_input.text() else None
                        imax = float(self.imax_input.text()) if self.imax_input.text() else None
                        ax.set_ylim(imin, imax)
            except ValueError:
                pass

        self.figure.tight_layout()
        self.canvas.draw()

    # ── Export ────────────────────────────────────────────────────────

    def export_csv(self):
        if not self.loaded_files:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if not file_path:
            return

        import pandas as pd
        frames = []
        for filename, data in self.loaded_files.items():
            df = pd.DataFrame({
                "time":     data.time.values,
                "voltage":  data.voltage.values,
                "current":  data.current.values,
                "filename": filename,
            })
            frames.append(df)

        pd.concat(frames, ignore_index=True).to_csv(file_path, index=False)
        self.status_label.setText("✓ Exported to CSV")

    def export_png(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", "", "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            self.figure.savefig(file_path, dpi=300, bbox_inches="tight")
            self.status_label.setText("✓ Plot saved")
