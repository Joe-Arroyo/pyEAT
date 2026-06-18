"""
Chronopotentiometry analysis tab
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QGroupBox, QComboBox, QLineEdit, QCheckBox, QRadioButton
)
from PyQt5.QtCore import Qt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure

from parsers.gamry import load_gamry_file
from parsers.autolab import (
    load_autolab_chronopotentiometry_ascii,
    load_autolab_chronopotentiometry_excel,
)
from parsers.riden import load_riden_file


# Maps combo index to (label, file_filter)
INSTRUMENTS = [
    ("Gamry (.DTA)",          "DTA Files (*.DTA);;All Files (*)"),
    ("Autolab ASCII (.txt)",  "Text Files (*.txt);;All Files (*)"),
    ("Autolab Excel (.xlsx)", "Excel Files (*.xlsx);;All Files (*)"),
    ("Riden RD6006 (.xlsx)",  "Excel Files (*.xlsx);;All Files (*)"),
]


class ChronopotentiometryTab(QWidget):
    """Tab for chronopotentiometry analysis"""

    def __init__(self):
        super().__init__()
        self.current_data = None
        self.init_ui()

    def init_ui(self):
        """Initialize UI components"""

        main_layout = QHBoxLayout(self)

        # ── Left panel ────────────────────────────────────────────────
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setMaximumWidth(400)

        # File loading group
        file_group = QGroupBox("📁 Load Data")
        file_layout = QVBoxLayout()

        file_layout.addWidget(QLabel("Instrument:"))
        self.instrument_combo = QComboBox()
        self.instrument_combo.addItems([label for label, _ in INSTRUMENTS])
        file_layout.addWidget(self.instrument_combo)

        self.load_btn = QPushButton("Open File")
        self.load_btn.clicked.connect(self.load_file)
        self.load_btn.setMinimumHeight(40)
        file_layout.addWidget(self.load_btn)

        self.file_label = QLabel("No file loaded")
        self.file_label.setWordWrap(True)
        self.file_label.setStyleSheet(
            "padding: 10px; background-color: #f0f0f0; border-radius: 5px;"
        )
        file_layout.addWidget(self.file_label)

        file_group.setLayout(file_layout)
        left_layout.addWidget(file_group)

        # Time filter group
        filter_group = QGroupBox("⏱️ Time Filter")
        filter_layout = QVBoxLayout()

        self.enable_filter = QCheckBox("Enable time filtering")
        filter_layout.addWidget(self.enable_filter)

        filter_layout.addWidget(QLabel("Min Time (s):"))
        self.time_min = QLineEdit()
        self.time_min.setPlaceholderText("e.g., 0")
        self.time_min.setEnabled(False)
        filter_layout.addWidget(self.time_min)

        filter_layout.addWidget(QLabel("Max Time (s):"))
        self.time_max = QLineEdit()
        self.time_max.setPlaceholderText("e.g., 1000")
        self.time_max.setEnabled(False)
        filter_layout.addWidget(self.time_max)

        self.apply_filter_btn = QPushButton("Apply Filter")
        self.apply_filter_btn.clicked.connect(self.apply_filter)
        self.apply_filter_btn.setEnabled(False)
        filter_layout.addWidget(self.apply_filter_btn)

        self.enable_filter.stateChanged.connect(self.toggle_filter)

        filter_group.setLayout(filter_layout)
        left_layout.addWidget(filter_group)

        # Plot selection group
        plot_group = QGroupBox("📊 Plot Selection")
        plot_layout = QVBoxLayout()

        self.plot_voltage_radio = QRadioButton("Voltage vs Time")
        self.plot_current_radio = QRadioButton("Current vs Time")
        self.plot_both_radio = QRadioButton("Both (2 subplots)")
        self.plot_both_radio.setChecked(True)

        plot_layout.addWidget(self.plot_voltage_radio)
        plot_layout.addWidget(self.plot_current_radio)
        plot_layout.addWidget(self.plot_both_radio)

        self.replot_btn = QPushButton("Update Plot")
        self.replot_btn.clicked.connect(self.update_plot)
        self.replot_btn.setEnabled(False)
        plot_layout.addWidget(self.replot_btn)

        plot_group.setLayout(plot_layout)
        left_layout.addWidget(plot_group)

        # Export group
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

        # ── Right panel ───────────────────────────────────────────────
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        self.figure = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        right_layout.addWidget(self.toolbar)
        right_layout.addWidget(self.canvas)

        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)

        self.show_empty_plot()

    # ── Helpers ───────────────────────────────────────────────────────

    def show_empty_plot(self):
        self.figure.clear()
        ax = self.figure.add_subplot(111)
        ax.text(
            0.5, 0.5,
            "Load a chronopotentiometry file to display data",
            ha="center", va="center", fontsize=14, color="gray",
        )
        ax.set_xticks([])
        ax.set_yticks([])
        self.canvas.draw()

    def toggle_filter(self, state):
        enabled = state == Qt.Checked
        self.time_min.setEnabled(enabled)
        self.time_max.setEnabled(enabled)

    def _set_controls_enabled(self, enabled: bool):
        self.apply_filter_btn.setEnabled(enabled)
        self.replot_btn.setEnabled(enabled)
        self.export_csv_btn.setEnabled(enabled)
        self.export_png_btn.setEnabled(enabled)

    # ── Loading ───────────────────────────────────────────────────────

    def load_file(self):
        idx = self.instrument_combo.currentIndex()
        label, file_filter = INSTRUMENTS[idx]

        file_path, _ = QFileDialog.getOpenFileName(
            self, f"Select {label} File", "", file_filter
        )
        if not file_path:
            return

        try:
            data = self._parse_file(idx, file_path)
        except Exception as e:
            self.file_label.setText(f"❌ Error: {e}")
            self.show_empty_plot()
            return

        if data is None:
            self.file_label.setText("❌ Failed to load file — check the console for details")
            self.show_empty_plot()
            self._set_controls_enabled(False)
            return

        self.current_data = data
        self.file_label.setText(f"✓ {data.source_file.name}")
        self._set_controls_enabled(True)
        self.plot_chronopotentiometry()

    def _parse_file(self, instrument_idx: int, file_path: str):
        if instrument_idx == 0:
            return load_gamry_file(file_path, technique="chronopotentiometry")
        elif instrument_idx == 1:
            return load_autolab_chronopotentiometry_ascii(file_path)
        elif instrument_idx == 2:
            return load_autolab_chronopotentiometry_excel(file_path)
        elif instrument_idx == 3:
            return load_riden_file(file_path, technique="chronopotentiometry")
        return None

    # ── Data ──────────────────────────────────────────────────────────

    def get_filtered_data(self):
        if self.current_data is None:
            return None

        data = self.current_data

        if self.enable_filter.isChecked():
            try:
                t_min = float(self.time_min.text()) if self.time_min.text() else data.time.min()
                t_max = float(self.time_max.text()) if self.time_max.text() else data.time.max()
                mask = (data.time >= t_min) & (data.time <= t_max)
                return {
                    "time": data.time[mask],
                    "voltage": data.voltage[mask],
                    "current": data.current[mask],
                }
            except ValueError:
                pass

        return {
            "time": data.time,
            "voltage": data.voltage,
            "current": data.current,
        }

    # ── Plotting ──────────────────────────────────────────────────────

    def plot_chronopotentiometry(self):
        data = self.get_filtered_data()
        if data is None:
            return

        self.figure.clear()

        if self.plot_both_radio.isChecked():
            ax1 = self.figure.add_subplot(211)
            ax2 = self.figure.add_subplot(212)

            ax1.plot(data["time"], data["voltage"], linewidth=1.5, color="blue")
            ax1.set_ylabel("Voltage (V)", fontsize=11)
            ax1.set_title("Voltage vs Time", fontsize=12, fontweight="bold")
            ax1.grid(True, alpha=0.3)

            ax2.plot(data["time"], data["current"], linewidth=1.5, color="red")
            ax2.set_xlabel("Time (s)", fontsize=11)
            ax2.set_ylabel("Current (A)", fontsize=11)
            ax2.set_title("Current vs Time", fontsize=12, fontweight="bold")
            ax2.grid(True, alpha=0.3)

        elif self.plot_voltage_radio.isChecked():
            ax = self.figure.add_subplot(111)
            ax.plot(data["time"], data["voltage"], linewidth=1.5, color="blue")
            ax.set_xlabel("Time (s)", fontsize=11)
            ax.set_ylabel("Voltage (V)", fontsize=11)
            ax.set_title("Voltage vs Time", fontsize=12, fontweight="bold")
            ax.grid(True, alpha=0.3)

        elif self.plot_current_radio.isChecked():
            ax = self.figure.add_subplot(111)
            ax.plot(data["time"], data["current"], linewidth=1.5, color="red")
            ax.set_xlabel("Time (s)", fontsize=11)
            ax.set_ylabel("Current (A)", fontsize=11)
            ax.set_title("Current vs Time", fontsize=12, fontweight="bold")
            ax.grid(True, alpha=0.3)

        self.figure.tight_layout()
        self.canvas.draw()

    def apply_filter(self):
        self.plot_chronopotentiometry()

    def update_plot(self):
        self.plot_chronopotentiometry()

    # ── Export ────────────────────────────────────────────────────────

    def export_csv(self):
        if self.current_data is None:
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save CSV", "", "CSV Files (*.csv);;All Files (*)"
        )
        if file_path:
            import pandas as pd
            data = self.get_filtered_data()
            pd.DataFrame(data).to_csv(file_path, index=False)
            self.file_label.setText("✓ Exported to CSV")

    def export_png(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Plot", "", "PNG Files (*.png);;All Files (*)"
        )
        if file_path:
            self.figure.savefig(file_path, dpi=300, bbox_inches="tight")
            self.file_label.setText("✓ Plot saved")