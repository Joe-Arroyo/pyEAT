"""
Polarization Curves analysis tab
Chronopotentiometry (Gamry) → Polarization curves
BUILT FROM SCRATCH - WORKING VERSION
Enhanced with interaction controls and CSV export options
Two-level hierarchy: Groups → Curves
"""

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QGroupBox, QLineEdit, QListWidget,
    QCheckBox, QListWidgetItem, QRadioButton,
    QScrollArea, QMessageBox, QInputDialog, QButtonGroup,
    QDialog, QComboBox, QSpinBox, QShortcut
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QKeySequence

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from matplotlib.gridspec import GridSpec

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path

from parsers.gamry import load_gamry_file
from parsers.autolab import (
    load_autolab_chronopotentiometry_ascii,
    load_autolab_chronopotentiometry_excel
)
from parsers.riden import load_riden_file
from parsers.custom_csv import load_custom_csv


# Configure matplotlib defaults for consistent legends
plt.rcParams['legend.fontsize'] = 14
plt.rcParams['legend.framealpha'] = 0.9
plt.rcParams['legend.fancybox'] = True
plt.rcParams['legend.shadow'] = False
plt.rcParams['legend.edgecolor'] = 'black'


class CSVExportDialog(QDialog):
    """Dialog for CSV export options"""

    def __init__(self, parent=None, groups=None):
        super().__init__(parent)
        self.groups = groups if groups else {}
        self.setWindowTitle("Export Data to CSV")
        self.setModal(True)
        self.setMinimumWidth(400)

        layout = QVBoxLayout(self)

        type_group = QGroupBox("Data Type")
        type_layout = QVBoxLayout()
        self.polar_radio = QRadioButton("Polarization Curves (processed data)")
        self.transient_radio = QRadioButton("Transient Data (raw time series)")
        self.polar_radio.setChecked(True)
        type_layout.addWidget(self.polar_radio)
        type_layout.addWidget(self.transient_radio)
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)

        group_group = QGroupBox("Groups to Export")
        group_layout = QVBoxLayout()
        self.group_checkboxes = {}
        if self.groups:
            for group_name, group_data in self.groups.items():
                if group_data['data'] is not None:
                    checkbox = QCheckBox(group_name)
                    checkbox.setChecked(True)
                    self.group_checkboxes[group_name] = checkbox
                    group_layout.addWidget(checkbox)
        if not self.group_checkboxes:
            no_data_label = QLabel("No curves with data available")
            no_data_label.setStyleSheet("color: gray; font-style: italic;")
            group_layout.addWidget(no_data_label)
        group_group.setLayout(group_layout)
        layout.addWidget(group_group)

        format_group = QGroupBox("Format Options")
        format_layout = QVBoxLayout()
        self.separate_files = QCheckBox("Separate file per group")
        self.separate_files.setChecked(False)
        format_layout.addWidget(self.separate_files)
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Export")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setEnabled(bool(self.group_checkboxes))
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def get_export_settings(self):
        selected_groups = [name for name, cb in self.group_checkboxes.items() if cb.isChecked()]
        return {
            'data_type': 'polarization' if self.polar_radio.isChecked() else 'transient',
            'groups': selected_groups,
            'separate_files': self.separate_files.isChecked()
        }


class PolarizationTab(QWidget):
    """
    Tab for analyzing chronopotentiometry data and building polarization curves.
    Two-level hierarchy: Groups (with visibility checkboxes) → Curves (data sources).
    """

    def __init__(self):
        super().__init__()

        # Two-level data storage
        # groups[gkey] = {'curves': {ckey: {'files': {}, 'data': None, 'steps': None}}, 'averaged_data': None}
        self.groups = {}
        self.active_group = None
        self.active_curve = None
        self.group_display_names = {}   # {gkey: display_label}
        self.curve_display_names = {}   # {gkey: {ckey: display_label}}
        self._label_to_source = {}      # {plot_label: (gkey, ckey_or_None)}
        self._source_curve_labels = set()

        self.colors = plt.cm.tab10(np.linspace(0, 1, 10))

        self.interaction_enabled = False
        self.edit_mode = False
        self.selected_point = None
        self.dragging = False
        self.drag_start_pos = None
        self.point_artists = {}

        self.undo_stack = []
        self.redo_stack = []
        self.max_undo_levels = 50

        self.transient_highlights = []
        self.selected_highlight = None

        self.init_ui()
        self.setup_shortcuts()

    def setup_shortcuts(self):
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo_action)
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo_action)

    def save_state(self):
        state = {}
        for gkey, gdata in self.groups.items():
            state[gkey] = {'curves': {}}
            for ckey, cdata in gdata['curves'].items():
                if cdata['data'] is not None:
                    state[gkey]['curves'][ckey] = {'data': cdata['data'].copy()}
            if gdata['averaged_data'] is not None:
                state[gkey]['averaged_data'] = gdata['averaged_data'].copy()
        self.undo_stack.append(state)
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)
        self.redo_stack.clear()
        self.update_undo_redo_buttons()

    def undo_action(self):
        if not self.undo_stack:
            return
        current_state = {}
        for gkey, gdata in self.groups.items():
            current_state[gkey] = {'curves': {}}
            for ckey, cdata in gdata['curves'].items():
                if cdata['data'] is not None:
                    current_state[gkey]['curves'][ckey] = {'data': cdata['data'].copy()}
            if gdata['averaged_data'] is not None:
                current_state[gkey]['averaged_data'] = gdata['averaged_data'].copy()
        self.redo_stack.append(current_state)
        previous_state = self.undo_stack.pop()
        for gkey, gstate in previous_state.items():
            if gkey in self.groups:
                for ckey, cstate in gstate.get('curves', {}).items():
                    if ckey in self.groups[gkey]['curves']:
                        self.groups[gkey]['curves'][ckey]['data'] = cstate['data'].copy()
                if 'averaged_data' in gstate:
                    self.groups[gkey]['averaged_data'] = gstate['averaged_data'].copy()
        self.selected_point = None
        self.edit_mode = False
        if hasattr(self, 'edit_mode_btn'):
            self.edit_mode_btn.setChecked(False)
        self.update_plot()
        self.update_undo_redo_buttons()
        if hasattr(self, 'load_status'):
            self.load_status.setText("✓ Undo completed")

    def redo_action(self):
        if not self.redo_stack:
            return
        current_state = {}
        for gkey, gdata in self.groups.items():
            current_state[gkey] = {'curves': {}}
            for ckey, cdata in gdata['curves'].items():
                if cdata['data'] is not None:
                    current_state[gkey]['curves'][ckey] = {'data': cdata['data'].copy()}
            if gdata['averaged_data'] is not None:
                current_state[gkey]['averaged_data'] = gdata['averaged_data'].copy()
        self.undo_stack.append(current_state)
        next_state = self.redo_stack.pop()
        for gkey, gstate in next_state.items():
            if gkey in self.groups:
                for ckey, cstate in gstate.get('curves', {}).items():
                    if ckey in self.groups[gkey]['curves']:
                        self.groups[gkey]['curves'][ckey]['data'] = cstate['data'].copy()
                if 'averaged_data' in gstate:
                    self.groups[gkey]['averaged_data'] = gstate['averaged_data'].copy()
        self.selected_point = None
        self.edit_mode = False
        if hasattr(self, 'edit_mode_btn'):
            self.edit_mode_btn.setChecked(False)
        self.update_plot()
        self.update_undo_redo_buttons()
        if hasattr(self, 'load_status'):
            self.load_status.setText("✓ Redo completed")

    def update_undo_redo_buttons(self):
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(len(self.undo_stack) > 0)
        if hasattr(self, 'redo_btn'):
            self.redo_btn.setEnabled(len(self.redo_stack) > 0)

    # ===================================================================
    # UI INITIALIZATION
    # ===================================================================

    def init_ui(self):
        main_layout = QHBoxLayout(self)
        left_panel = self.create_left_panel()
        right_panel = self.create_right_panel()
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        self.empty_plot()

    def create_left_panel(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(600)

        container = QWidget()
        layout = QVBoxLayout(container)

        layout.addWidget(self.create_group_section())
        layout.addWidget(self.create_curves_section())
        layout.addWidget(self.create_load_section())
        layout.addWidget(self.create_processing_section())
        layout.addWidget(self.create_interaction_section())
        layout.addWidget(self.create_plot_section())
        layout.addWidget(self.create_export_section())

        layout.addStretch()
        scroll.setWidget(container)
        return scroll

    def create_group_section(self):
        """Groups with visibility checkboxes"""
        box = QGroupBox("🗂️ Groups")
        layout = QVBoxLayout()

        btn_layout = QHBoxLayout()
        self.new_group_btn = QPushButton("+ New Group")
        self.new_group_btn.clicked.connect(self.create_new_group)
        btn_layout.addWidget(self.new_group_btn)
        self.del_group_btn = QPushButton("Remove Group")
        self.del_group_btn.clicked.connect(self.remove_group)
        btn_layout.addWidget(self.del_group_btn)
        layout.addLayout(btn_layout)

        self.group_list = QListWidget()
        self.group_list.itemChanged.connect(self.on_group_item_changed)
        self.group_list.currentItemChanged.connect(self.on_group_selected)
        self.group_list.itemDoubleClicked.connect(self._start_group_rename)
        layout.addWidget(self.group_list)

        self.group_status = QLabel("Create a group to start")
        self.group_status.setWordWrap(True)
        self.group_status.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.group_status)

        box.setLayout(layout)
        return box

    def create_curves_section(self):
        """Curves within the active group (no checkboxes)"""
        box = QGroupBox("🏷️ Curves")
        layout = QVBoxLayout()

        btn_layout = QHBoxLayout()
        self.new_curve_btn = QPushButton("+ New Curve")
        self.new_curve_btn.clicked.connect(self.create_new_curve)
        btn_layout.addWidget(self.new_curve_btn)
        self.avg_curves_btn = QPushButton("Average Curves")
        self.avg_curves_btn.setToolTip("Average all curves in the active group into one curve with error bars")
        self.avg_curves_btn.clicked.connect(self.compute_averaged_curve)
        btn_layout.addWidget(self.avg_curves_btn)
        self.remove_avg_btn = QPushButton("Remove Average")
        self.remove_avg_btn.setToolTip("Remove the averaged curve and go back to source curves")
        self.remove_avg_btn.clicked.connect(self.remove_averaged_curve)
        btn_layout.addWidget(self.remove_avg_btn)
        self.del_curve_btn = QPushButton("Remove Curve")
        self.del_curve_btn.clicked.connect(self.remove_curve)
        btn_layout.addWidget(self.del_curve_btn)
        layout.addLayout(btn_layout)

        self.curve_list = QListWidget()
        self.curve_list.currentItemChanged.connect(self.on_curve_selected)
        self.curve_list.itemDoubleClicked.connect(self._start_curve_rename)
        self.curve_list.itemChanged.connect(self.on_curve_item_changed)
        layout.addWidget(self.curve_list)

        self.show_source_curves_cb = QCheckBox("Show source curves when averaged")
        self.show_source_curves_cb.setToolTip("Overlay individual source curves alongside the averaged curve")
        self.show_source_curves_cb.stateChanged.connect(self.update_plot)
        layout.addWidget(self.show_source_curves_cb)

        self.curve_status = QLabel("Select a group first")
        self.curve_status.setWordWrap(True)
        self.curve_status.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.curve_status)

        box.setLayout(layout)
        return box

    def create_load_section(self):
        box = QGroupBox("📁 Load Data")
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Instrument:"))
        self.instrument_combo = QComboBox()
        self.instrument_combo.addItems([
            "Gamry (.DTA)",
            "Autolab ASCII (.txt)",
            "Autolab Excel (.xlsx)",
            "Riden RD6006 (.xlsx)",
            "Custom CSV (V,I,P,t)"
        ])
        layout.addWidget(self.instrument_combo)

        self.load_btn = QPushButton("Load Folder into Curve")
        self.load_btn.clicked.connect(self.load_folder)
        layout.addWidget(self.load_btn)

        self.load_file_btn = QPushButton("Load Single File into Curve")
        self.load_file_btn.clicked.connect(self.load_single_file)
        layout.addWidget(self.load_file_btn)

        self.load_status = QLabel("No data loaded")
        self.load_status.setWordWrap(True)
        self.load_status.setStyleSheet("color: gray;")
        layout.addWidget(self.load_status)

        box.setLayout(layout)
        return box

    def create_processing_section(self):
        box = QGroupBox("⚙️ Processing Parameters")
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Averaging time [s]:"))
        self.avg_time_input = QLineEdit("30")
        self.avg_time_input.setToolTip("Time window for steady-state averaging (from end of step)")
        layout.addWidget(self.avg_time_input)

        layout.addWidget(QLabel("Electrode area [cm²]:"))
        self.area_input = QLineEdit("1.0")
        self.area_input.setToolTip("Electrode area for current density calculation")
        layout.addWidget(self.area_input)

        self.apply_curve_btn = QPushButton("Apply to This Curve")
        self.apply_curve_btn.setToolTip("Reprocess only the currently selected curve")
        self.apply_curve_btn.clicked.connect(self.on_apply_this_curve)
        layout.addWidget(self.apply_curve_btn)

        self.apply_group_btn = QPushButton("Apply to Group")
        self.apply_group_btn.setToolTip("Reprocess all curves in the active group")
        self.apply_group_btn.clicked.connect(self.on_apply_group)
        layout.addWidget(self.apply_group_btn)

        self.apply_all_btn = QPushButton("Apply to All Groups")
        self.apply_all_btn.setToolTip("Reprocess all curves in all groups")
        self.apply_all_btn.clicked.connect(self.on_parameters_changed)
        layout.addWidget(self.apply_all_btn)

        box.setLayout(layout)
        return box

    def create_interaction_section(self):
        box = QGroupBox("🎯 Data Interaction")
        layout = QVBoxLayout()

        self.enable_interaction_cb = QCheckBox("Enable data interaction")
        self.enable_interaction_cb.setToolTip("Enable point selection and editing on plots")
        self.enable_interaction_cb.stateChanged.connect(self.toggle_interaction)
        layout.addWidget(self.enable_interaction_cb)

        self.interaction_controls = QWidget()
        interaction_layout = QVBoxLayout(self.interaction_controls)
        interaction_layout.setContentsMargins(20, 5, 0, 5)

        self.edit_mode_btn = QPushButton("🔧 Enable Edit Mode")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.setToolTip("Click to edit data points by dragging")
        self.edit_mode_btn.clicked.connect(self.toggle_edit_mode)
        interaction_layout.addWidget(self.edit_mode_btn)

        undo_redo_layout = QHBoxLayout()
        self.undo_btn = QPushButton("↶ Undo")
        self.undo_btn.setToolTip("Undo last change (Ctrl+Z)")
        self.undo_btn.clicked.connect(self.undo_action)
        self.undo_btn.setEnabled(False)
        undo_redo_layout.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("↷ Redo")
        self.redo_btn.setToolTip("Redo last undone change (Ctrl+Y)")
        self.redo_btn.clicked.connect(self.redo_action)
        self.redo_btn.setEnabled(False)
        undo_redo_layout.addWidget(self.redo_btn)
        interaction_layout.addLayout(undo_redo_layout)

        self.interaction_status = QLabel("Select a point to see details")
        self.interaction_status.setWordWrap(True)
        self.interaction_status.setStyleSheet("color: gray; font-size: 9px;")
        interaction_layout.addWidget(self.interaction_status)

        self.interaction_controls.setVisible(False)
        layout.addWidget(self.interaction_controls)

        box.setLayout(layout)
        return box

    def create_plot_section(self):
        box = QGroupBox("📊 Plot Options")
        layout = QVBoxLayout()

        layout.addWidget(QLabel("Plot type:"))
        self.plot_type_group = QButtonGroup(self)
        self.radio_polar_only = QRadioButton("Polarization only")
        self.radio_with_transient = QRadioButton("With voltage transients")
        self.plot_type_group.addButton(self.radio_polar_only)
        self.plot_type_group.addButton(self.radio_with_transient)
        self.radio_polar_only.setChecked(True)
        self.radio_polar_only.toggled.connect(self.update_plot)
        self.radio_with_transient.toggled.connect(self.update_plot)
        layout.addWidget(self.radio_polar_only)
        layout.addWidget(self.radio_with_transient)

        layout.addWidget(QLabel("Multi-group layout:"))
        self.layout_type_group = QButtonGroup(self)
        self.radio_overlay = QRadioButton("Overlay")
        self.radio_grid = QRadioButton("Grid")
        self.layout_type_group.addButton(self.radio_overlay)
        self.layout_type_group.addButton(self.radio_grid)
        self.radio_overlay.setChecked(True)
        self.radio_overlay.toggled.connect(self.update_plot)
        self.radio_grid.toggled.connect(self.update_plot)
        layout.addWidget(self.radio_overlay)
        layout.addWidget(self.radio_grid)

        box.setLayout(layout)
        return box

    def create_export_section(self):
        box = QGroupBox("💾 Export")
        layout = QVBoxLayout()

        self.export_csv_btn = QPushButton("Export Data as CSV...")
        self.export_csv_btn.setToolTip("Export polarization or transient data to CSV")
        self.export_csv_btn.clicked.connect(self.export_csv_data)
        self.export_csv_btn.setEnabled(False)
        layout.addWidget(self.export_csv_btn)

        self.export_plot_btn = QPushButton("Export Plot...")
        self.export_plot_btn.setToolTip("Export current plot with custom size and DPI")
        self.export_plot_btn.clicked.connect(self.export_plot)
        self.export_plot_btn.setEnabled(False)
        layout.addWidget(self.export_plot_btn)

        box.setLayout(layout)
        return box

    def create_right_panel(self):
        container = QWidget()
        layout = QVBoxLayout(container)

        self.fig = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)

        self.canvas.mpl_connect('button_press_event', self.on_plot_click)
        self.canvas.mpl_connect('button_release_event', self.on_plot_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_plot_motion)

        self.selected_annotation = None

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        return container

    # ===================================================================
    # INTERACTION CONTROLS
    # ===================================================================

    def toggle_interaction(self, state):
        self.interaction_enabled = state == Qt.Checked
        self.interaction_controls.setVisible(self.interaction_enabled)
        if not self.interaction_enabled:
            self.selected_point = None
            self.edit_mode = False
            self.edit_mode_btn.setChecked(False)
            self.clear_selection_visual()
            self.interaction_status.setText("Interaction disabled")
        else:
            self.interaction_status.setText("Select a point to see details")
        self.update_plot()

    def toggle_edit_mode(self, checked):
        if not self.interaction_enabled:
            self.edit_mode_btn.setChecked(False)
            return
        self.edit_mode = checked
        if self.edit_mode:
            self.edit_mode_btn.setText("🔧 Edit Mode: ON")
            self.edit_mode_btn.setStyleSheet("background-color: #ffeb3b; font-weight: bold;")
            self.interaction_status.setText("Edit mode ON - Drag points to modify values")
        else:
            self.edit_mode_btn.setText("🔧 Enable Edit Mode")
            self.edit_mode_btn.setStyleSheet("")
            self.interaction_status.setText("Edit mode OFF - Click points for information")
            self.selected_point = None
            self.clear_selection_visual()

    def highlight_current_step_in_transient(self, selected_point):
        if not self.radio_with_transient.isChecked():
            return

        for artist in self.transient_highlights:
            try:
                artist.remove()
            except Exception:
                pass
        self.transient_highlights.clear()

        group_display = selected_point['group']
        gkey, ckey = self._display_to_key(group_display)
        I_mean = selected_point['I']

        # Averaged curves have no step data
        if ckey is None or gkey not in self.groups:
            return

        curve = self.groups[gkey]['curves'].get(ckey, {})
        steps = curve.get('steps')
        data = curve.get('data')

        if not steps or data is None:
            return

        transient_ax = None
        for ax in self.fig.get_axes():
            title = ax.get_title()
            xlabel = ax.get_xlabel()
            ylabel = ax.get_ylabel()
            if 'Voltage Transients' in title:
                transient_ax = ax
                break
            elif 'Time' in xlabel and 'Voltage' in ylabel:
                transient_ax = ax
                break

        if transient_ax is None:
            return

        time_offset = 0
        found_step = False

        for filename in sorted(steps.keys()):
            file_steps = steps[filename]
            for step in file_steps:
                step_I_mean = step['I_mean']
                t = step['time_rel'] + time_offset

                if np.abs(step_I_mean - I_mean) / np.abs(I_mean) < 0.01:
                    highlight = transient_ax.axvspan(t[0], t[-1], alpha=0.3, color='orange', zorder=0)
                    self.transient_highlights.append(highlight)
                    text_y = transient_ax.get_ylim()[1] * 0.95
                    text = transient_ax.text(
                        (t[0] + t[-1]) / 2, text_y,
                        f'I = {I_mean*1000:.1f} mA',
                        ha='center', va='top', fontsize=10, fontweight='bold', color='red',
                        bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8)
                    )
                    self.transient_highlights.append(text)
                    found_step = True
                    break

                time_offset = t[-1] if len(step['time_rel']) > 0 else time_offset

            if found_step:
                break

        self.canvas.draw_idle()

    def clear_selection_visual(self):
        if self.selected_annotation is not None:
            try:
                self.selected_annotation.remove()
            except Exception:
                pass
            self.selected_annotation = None

        if self.selected_highlight is not None:
            try:
                self.selected_highlight.remove()
            except Exception:
                pass
            self.selected_highlight = None
        self.canvas.draw_idle()

        for ax in self.fig.get_axes():
            for artist in ax.lines[:]:
                if getattr(artist, '_temp_highlight', False):
                    try:
                        artist.remove()
                    except Exception:
                        pass

        for artist in self.transient_highlights:
            try:
                artist.remove()
            except Exception:
                pass
        self.transient_highlights.clear()

        for ax in self.fig.get_axes():
            for artist in ax.get_children():
                if hasattr(artist, '_temp_highlight') and artist._temp_highlight:
                    try:
                        artist.remove()
                    except Exception:
                        pass

        self.canvas.draw_idle()

    # ===================================================================
    # GROUP MANAGEMENT
    # ===================================================================

    def create_new_group(self):
        group_number = len(self.groups) + 1
        gkey = f"Group {group_number}"
        self.groups[gkey] = {'curves': {}, 'averaged_data': None}
        self.group_display_names[gkey] = gkey
        self.curve_display_names[gkey] = {}

        item = QListWidgetItem(gkey)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        item.setData(Qt.UserRole, gkey)
        self.group_list.addItem(item)
        self.group_list.setCurrentItem(item)

        self.active_group = gkey
        self.active_curve = None
        self.group_status.setText(f"Active: {gkey}")
        self.curve_list.clear()
        self.curve_status.setText("Create a curve in this group")
        self.update_export_buttons()
        print(f"OK Created {gkey}")

    def remove_group(self):
        item = self.group_list.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select a group to remove")
            return

        gkey = item.data(Qt.UserRole) or item.text()
        display = self.group_display_names.get(gkey, gkey)

        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Remove group '{display}' and all its curves and data?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.groups.pop(gkey, None)
            self.group_display_names.pop(gkey, None)
            self.curve_display_names.pop(gkey, None)
            self.group_list.takeItem(self.group_list.row(item))

            if self.active_group == gkey:
                self.active_group = None
                self.active_curve = None
                self.curve_list.clear()
                self.curve_status.setText("Select a group")

            self.update_export_buttons()
            self.update_plot()
            print(f"OK Removed group {display}")

    def _start_group_rename(self, item):
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.group_list.editItem(item)

    def on_group_selected(self, current, previous):
        if current:
            gkey = current.data(Qt.UserRole) or current.text()
            self.active_group = gkey
            display = self.group_display_names.get(gkey, gkey)
            self.group_status.setText(f"Active: {display}")
            self._refresh_curve_list(gkey)
            self.update_plot()

    def on_group_item_changed(self, item):
        gkey = item.data(Qt.UserRole)
        if gkey is None:
            return
        new_text = item.text()
        old_display = self.group_display_names.get(gkey, gkey)
        if new_text != old_display:
            self.group_display_names[gkey] = new_text
            if self.active_group == gkey:
                self.group_status.setText(f"Active: {new_text}")
        self.update_plot()

    def _refresh_curve_list(self, gkey):
        self.curve_list.blockSignals(True)
        self.curve_list.clear()
        if gkey in self.groups:
            for ckey, cdisplay in self.curve_display_names.get(gkey, {}).items():
                item = QListWidgetItem(cdisplay)
                item.setData(Qt.UserRole, ckey)
                self.curve_list.addItem(item)
        self.curve_list.blockSignals(False)
        self.active_curve = None
        self.curve_status.setText("Select or create a curve")

    # ===================================================================
    # CURVE MANAGEMENT
    # ===================================================================

    def create_new_curve(self):
        if not self.active_group:
            QMessageBox.warning(self, "No Group Selected", "Please create and select a group first")
            return

        gkey = self.active_group
        curve_number = len(self.groups[gkey]['curves']) + 1
        ckey = f"_curve_{curve_number}_{gkey}"
        cdisplay = f"Curve {curve_number}"

        self.groups[gkey]['curves'][ckey] = {'files': {}, 'data': None, 'steps': None}
        self.curve_display_names[gkey][ckey] = cdisplay

        item = QListWidgetItem(cdisplay)
        item.setData(Qt.UserRole, ckey)
        self.curve_list.addItem(item)
        self.curve_list.setCurrentItem(item)

        self.active_curve = ckey
        self.curve_status.setText(f"Active: {cdisplay}")
        print(f"OK Created {cdisplay} in {gkey}")

    def remove_curve(self):
        item = self.curve_list.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select a curve to remove")
            return

        if not self.active_group:
            return

        gkey = self.active_group
        ckey = item.data(Qt.UserRole) or item.text()
        cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)

        reply = QMessageBox.question(
            self, "Confirm Deletion",
            f"Remove curve '{cdisplay}' and its data?",
            QMessageBox.Yes | QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.groups[gkey]['curves'].pop(ckey, None)
            self.curve_display_names[gkey].pop(ckey, None)
            # Clear averaged data since source curves changed
            self.groups[gkey]['averaged_data'] = None
            self.curve_list.takeItem(self.curve_list.row(item))

            if self.active_curve == ckey:
                self.active_curve = None
                self.curve_status.setText("Select or create a curve")

            self.update_export_buttons()
            self.update_plot()
            print(f"OK Removed curve {cdisplay}")

    def _start_curve_rename(self, item):
        item.setFlags(item.flags() | Qt.ItemIsEditable)
        self.curve_list.editItem(item)

    def on_curve_selected(self, current, previous):
        if current:
            ckey = current.data(Qt.UserRole) or current.text()
            self.active_curve = ckey
            gkey = self.active_group
            cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey) if gkey else ckey
            self.curve_status.setText(f"Active: {cdisplay}")

    def on_curve_item_changed(self, item):
        ckey = item.data(Qt.UserRole)
        if ckey is None:
            return
        gkey = self.active_group
        if gkey is None:
            return
        new_text = item.text()
        old_display = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
        if new_text != old_display:
            self.curve_display_names[gkey][ckey] = new_text
            if self.active_curve == ckey:
                self.curve_status.setText(f"Active: {new_text}")
        self.update_plot()

    # ===================================================================
    # DATA LOADING
    # ===================================================================

    def load_folder(self):
        if not self.active_group or not self.active_curve:
            QMessageBox.warning(
                self, "No Curve Selected",
                "Please create and select a group and curve first"
            )
            return

        instrument = self.instrument_combo.currentText()

        if "Gamry" in instrument:
            dialog_title = "Select Folder with .DTA Files"
        elif "ASCII" in instrument:
            dialog_title = "Select Folder with .txt Files"
        elif "Riden" in instrument or "Autolab" in instrument:
            dialog_title = "Select Folder with .xlsx Files"
        else:
            dialog_title = "Select Folder with .csv Files"

        folder = QFileDialog.getExistingDirectory(self, dialog_title)
        if not folder:
            return

        folder_path = Path(folder)

        if "Gamry" in instrument:
            data_files = list(folder_path.glob("*.DTA"))
        elif "ASCII" in instrument:
            data_files = list(folder_path.glob("*.txt"))
        elif "Custom CSV" in instrument:
            data_files = list(folder_path.glob("*.csv"))
        else:
            data_files = list(folder_path.glob("*.xlsx"))

        if not data_files:
            ext = ".DTA" if "Gamry" in instrument else ".txt" if "ASCII" in instrument else ".csv" if "Custom" in instrument else ".xlsx"
            QMessageBox.warning(self, "No Files Found", f"No {ext} files found in the selected folder")
            return

        print(f"\nLOAD Loading files from: {folder}")

        loaded_files = {}
        for file_path in sorted(data_files):
            try:
                if "Gamry" in instrument:
                    data = load_gamry_file(file_path)
                elif "ASCII" in instrument:
                    data = load_autolab_chronopotentiometry_ascii(file_path)
                elif "Custom CSV" in instrument:
                    data = load_custom_csv(file_path)
                elif "Riden" in instrument:
                    data = load_riden_file(file_path)
                else:
                    data = load_autolab_chronopotentiometry_excel(file_path)
                loaded_files[file_path.name] = data
                print(f"  OK {file_path.name}")
            except Exception as e:
                print(f"  ERROR {file_path.name}: {e}")

        if not loaded_files:
            QMessageBox.warning(self, "Loading Failed", "Failed to load any files from the folder")
            return

        gkey = self.active_group
        ckey = self.active_curve
        self.groups[gkey]['curves'][ckey]['files'] = loaded_files
        self.process_curve(gkey, ckey)

        cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
        self.load_status.setText(f"Loaded {len(loaded_files)} files into {cdisplay}")
        self.load_status.setStyleSheet("color: green;")
        self.update_export_buttons()
        self.update_plot()
        print(f"OK Loaded {len(loaded_files)} files into {cdisplay}")

    def load_single_file(self):
        if not self.active_group or not self.active_curve:
            QMessageBox.warning(
                self, "No Curve Selected",
                "Please create and select a group and curve first"
            )
            return

        instrument = self.instrument_combo.currentText()

        if "Gamry" in instrument:
            file_filter = "DTA Files (*.DTA);;All Files (*)"
            dialog_title = "Select .DTA File"
        elif "ASCII" in instrument:
            file_filter = "Text Files (*.txt);;All Files (*)"
            dialog_title = "Select .txt File"
        elif "Custom CSV" in instrument:
            file_filter = "CSV Files (*.csv);;All Files (*)"
            dialog_title = "Select .csv File"
        else:
            file_filter = "Excel Files (*.xlsx);;All Files (*)"
            dialog_title = "Select .xlsx File"

        file_path, _ = QFileDialog.getOpenFileName(self, dialog_title, "", file_filter)
        if not file_path:
            return

        file_path = Path(file_path)
        print(f"\nLOAD Loading single file: {file_path}")

        try:
            if "Gamry" in instrument:
                data = load_gamry_file(file_path)
            elif "ASCII" in instrument:
                data = load_autolab_chronopotentiometry_ascii(file_path)
            elif "Custom CSV" in instrument:
                data = load_custom_csv(file_path)
            elif "Autolab" in instrument:
                data = load_autolab_chronopotentiometry_excel(file_path)
            elif "Riden" in instrument:
                data = load_riden_file(file_path, technique='chronopotentiometry')
            else:
                raise ValueError(f"Unknown instrument type: {instrument}")

            if data:
                gkey = self.active_group
                ckey = self.active_curve
                self.groups[gkey]['curves'][ckey]['files'] = {file_path.name: data}
                self.process_curve(gkey, ckey)

                cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
                self.load_status.setText(f"Loaded {file_path.name} into {cdisplay}")
                self.load_status.setStyleSheet("color: green;")
                self.update_export_buttons()
                self.update_plot()
                print(f"OK Loaded {file_path.name} into {cdisplay}")
            else:
                QMessageBox.warning(self, "Loading Failed", f"Failed to load {file_path.name}")

        except Exception as e:
            QMessageBox.critical(self, "Loading Error", f"Error loading {file_path.name}:\n{str(e)}")
            import traceback
            traceback.print_exc()

    def update_export_buttons(self):
        has_data = (
            any(
                cdata['data'] is not None
                for gdata in self.groups.values()
                for cdata in gdata['curves'].values()
            ) or any(
                gdata['averaged_data'] is not None
                for gdata in self.groups.values()
            )
        )
        self.export_csv_btn.setEnabled(has_data)
        self.export_plot_btn.setEnabled(has_data)

    # ===================================================================
    # DATA PROCESSING
    # ===================================================================

    def process_curve(self, gkey, ckey):
        """Process chronopotentiometry files to extract polarization curve for one curve"""
        curve = self.groups[gkey]['curves'][ckey]
        files = curve['files']

        if not files:
            return

        cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
        print(f"\n⚙️ Processing {cdisplay}...")

        try:
            avg_time = float(self.avg_time_input.text())
            electrode_area = float(self.area_input.text())
        except ValueError:
            print("  ERROR Invalid parameters")
            return

        polarization_data = []
        step_data = {}

        for filename, data_obj in files.items():
            if not hasattr(data_obj, 'time') or not hasattr(data_obj, 'voltage') or not hasattr(data_obj, 'current'):
                print(f"  ERROR {filename}: Missing required attributes")
                continue

            time = pd.to_numeric(data_obj.time.astype(str).str.replace(',', '.'), errors='coerce').values
            voltage = pd.to_numeric(data_obj.voltage.astype(str).str.replace(',', '.'), errors='coerce').values
            current = pd.to_numeric(data_obj.current.astype(str).str.replace(',', '.'), errors='coerce').values

            valid_mask = ~(np.isnan(time) | np.isnan(voltage) | np.isnan(current))
            time = time[valid_mask]
            voltage = voltage[valid_mask]
            current = current[valid_mask]

            if len(time) < 5:
                print(f"  ERROR {filename}: Insufficient data points")
                continue

            print(f"  DATA {filename}: {len(time)} points")

            steps = self.detect_current_steps(time, current, voltage)

            if not steps:
                print(f"     WARNING  No valid steps detected")
                continue

            print(f"     OK Detected {len(steps)} step(s)")
            step_data[filename] = steps

            for step_num, step in enumerate(steps, 1):
                steady_time = min(avg_time, step['duration'])
                time_threshold = step['time_rel'][-1] - steady_time
                steady_mask = step['time_rel'] >= time_threshold

                if steady_mask.sum() < 3:
                    print(f"     WARNING  Step {step_num}: Too few steady-state points")
                    continue

                current_density = step['I_mean'] / electrode_area if electrode_area != 0 else step['I_mean']
                voltage_avg = np.mean(step['voltage'][steady_mask])
                voltage_std = np.std(step['voltage'][steady_mask], ddof=1)
                n_samples = steady_mask.sum()
                voltage_sterr = voltage_std / np.sqrt(n_samples)

                polarization_data.append({
                    'file': filename,
                    'step': step_num,
                    'j': current_density,
                    'I_mean': step['I_mean'],
                    'V': voltage_avg,
                    'V_std': voltage_sterr,
                    'steady_start': time_threshold,
                    'steady_duration': steady_time
                })

                print(f"     OK Step {step_num}: j={current_density:.4f} A/cm², V={voltage_avg:.3f} V")

        if polarization_data:
            df_polar = pd.DataFrame(polarization_data).sort_values('j')
            curve['data'] = df_polar
            curve['steps'] = step_data
            # Clear group average since source curves changed
            self.groups[gkey]['averaged_data'] = None
            print(f"OK Extracted {len(df_polar)} polarization points")
        else:
            curve['data'] = None
            curve['steps'] = None
            print("ERROR No polarization data extracted")

    def remove_averaged_curve(self):
        if not self.active_group:
            QMessageBox.warning(self, "No Group Selected", "Please select a group first.")
            return
        gkey = self.active_group
        if self.groups[gkey]['averaged_data'] is None:
            QMessageBox.information(self, "No Average", "This group has no averaged curve.")
            return
        self.groups[gkey]['averaged_data'] = None
        gdisplay = self.group_display_names.get(gkey, gkey)
        self.group_status.setText(f"Active: {gdisplay}")
        self.update_plot()

    def compute_averaged_curve(self):
        """Average all curves with data within the active group"""
        if not self.active_group:
            QMessageBox.warning(self, "No Group Selected", "Please select a group first")
            return

        gkey = self.active_group
        curves_with_data = []

        for ckey, cdata in self.groups[gkey]['curves'].items():
            if cdata['data'] is not None:
                cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
                df = cdata['data'].sort_values('j').reset_index(drop=True)
                curves_with_data.append({'display': cdisplay, 'j': df['j'].values, 'v': df['V'].values, 'n': len(df)})

        if len(curves_with_data) < 2:
            QMessageBox.warning(
                self, "Not enough curves",
                "Need at least 2 curves with processed data in this group to compute an average."
            )
            return

        n_steps = min(c['n'] for c in curves_with_data)
        if n_steps == 0:
            QMessageBox.warning(self, "Empty curves", "One or more curves have no steps.")
            return

        j_arrays = [c['j'][:n_steps] for c in curves_with_data]
        v_arrays = [c['v'][:n_steps] for c in curves_with_data]
        n_curves = len(curves_with_data)

        j_mean = np.mean(j_arrays, axis=0)
        v_mean = np.mean(v_arrays, axis=0)
        v_std = np.std(v_arrays, axis=0, ddof=1)

        area = float(self.area_input.text() or 1.0)
        avg_df = pd.DataFrame({
            'file': [f"avg({n_curves} curves)"] * n_steps,
            'step': np.arange(1, n_steps + 1),
            'j': j_mean,
            'I_mean': j_mean * area if area != 0 else j_mean,
            'V': v_mean,
            'V_std': v_std,
            'N_curves': [n_curves] * n_steps,
            'steady_start': [np.nan] * n_steps,
            'steady_duration': [np.nan] * n_steps,
        })

        self.groups[gkey]['averaged_data'] = avg_df
        gdisplay = self.group_display_names.get(gkey, gkey)
        self.group_status.setText(f"Active: {gdisplay} (averaged, n={n_curves})")
        self.update_plot()
        print(f"OK Averaged {n_curves} curves in '{gdisplay}' ({n_steps} points)")

    def detect_current_steps(self, time, current, voltage, min_duration=5, tolerance=0.05):
        if len(time) < 10:
            return []

        diff = np.abs(np.diff(current))
        threshold = 0.0008

        change_indices = np.where(diff > threshold)[0]

        if len(change_indices) > 0:
            grouped = [change_indices[0]]
            for idx in change_indices[1:]:
                if idx - grouped[-1] > 10:
                    grouped.append(idx)
            change_indices = np.array(grouped)

        change_indices = np.unique(np.concatenate([[0], change_indices + 1, [len(time) - 1]]))

        steps = []

        for i in range(len(change_indices) - 1):
            start_idx = change_indices[i]
            end_idx = change_indices[i + 1]

            if end_idx - start_idx < 5:
                continue

            seg_time = time[start_idx:end_idx]
            seg_current = current[start_idx:end_idx]
            seg_voltage = voltage[start_idx:end_idx]

            duration = seg_time[-1] - seg_time[0]
            I_mean = np.mean(seg_current)
            I_std = np.std(seg_current)
            variation = I_std / abs(I_mean) if abs(I_mean) > 0.01 else I_std

            if duration >= min_duration and variation < tolerance:
                steps.append({
                    'time': seg_time,
                    'time_rel': seg_time - seg_time[0],
                    'current': seg_current,
                    'voltage': seg_voltage,
                    'duration': duration,
                    'I_mean': I_mean,
                    'I_std': I_std,
                    'start_time': seg_time[0],
                    'end_time': seg_time[-1]
                })

        if not steps and len(time) > 20:
            duration = time[-1] - time[0]
            I_mean = np.mean(current)
            variation = np.std(current) / abs(I_mean) if I_mean != 0 else 0

            if duration >= min_duration and variation < tolerance * 2:
                steps.append({
                    'time': time,
                    'time_rel': time - time[0],
                    'current': current,
                    'voltage': voltage,
                    'duration': duration,
                    'I_mean': I_mean,
                    'I_std': np.std(current),
                    'start_time': time[0],
                    'end_time': time[-1]
                })

        return steps

    def on_parameters_changed(self):
        for gkey, gdata in self.groups.items():
            for ckey, cdata in gdata['curves'].items():
                if cdata['files']:
                    self.process_curve(gkey, ckey)
        self.update_plot()

    def on_apply_this_curve(self):
        if not self.active_group or not self.active_curve:
            QMessageBox.warning(self, "No Curve Selected", "Select a curve first.")
            return
        cdata = self.groups[self.active_group]['curves'].get(self.active_curve, {})
        if cdata.get('files'):
            self.process_curve(self.active_group, self.active_curve)
        self.update_plot()

    def on_apply_group(self):
        if not self.active_group:
            QMessageBox.warning(self, "No Group Selected", "Select a group first.")
            return
        gdata = self.groups[self.active_group]
        for ckey, cdata in gdata['curves'].items():
            if cdata['files']:
                self.process_curve(self.active_group, ckey)
        self.update_plot()

    # ===================================================================
    # PLOT INTERACTION
    # ===================================================================

    def on_plot_click(self, event):
        if not self.interaction_enabled or event.button != 1 or event.inaxes is None:
            return

        ax = event.inaxes

        if self.selected_annotation is not None:
            try:
                self.selected_annotation.remove()
            except Exception:
                pass
        self.selected_annotation = None
        if self.selected_highlight is not None:
            try:
                self.selected_highlight.remove()
            except Exception:
                pass
            self.selected_highlight = None
        self.canvas.draw_idle()

        visible_groups = self.get_visible_groups()
        if not visible_groups:
            return

        min_distance = float('inf')
        closest_point = None

        for name, group, _color in visible_groups:
            data = group['data']
            if data is None or len(data) == 0:
                continue

            j_ma = self._x_values(data)
            V = data['V'].values
            I_mean = data['I_mean'].values

            for i in range(len(j_ma)):
                try:
                    dx = (j_ma[i] - event.xdata) / (ax.get_xlim()[1] - ax.get_xlim()[0])
                    dy = (V[i] - event.ydata) / (ax.get_ylim()[1] - ax.get_ylim()[0])
                    distance = (dx**2 + dy**2)**0.5

                    if distance < min_distance and distance < 0.05:
                        min_distance = distance
                        closest_point = {
                            'group': name,
                            'index': i,
                            'j_ma': j_ma[i],
                            'j_A': data['j'].values[i],
                            'V': V[i],
                            'I': I_mean[i],
                            'name': name,
                            'ax': ax
                        }
                except Exception:
                    continue

        if closest_point:
            self.selected_point = closest_point
            self.show_point_info(closest_point)
            self.highlight_current_step_in_transient(closest_point)

            if self.edit_mode:
                self.dragging = True
                self.drag_start_pos = (event.xdata, event.ydata)

    def on_plot_motion(self, event):
        if not self.interaction_enabled or not self.edit_mode or not self.dragging:
            return
        if self.selected_point is None or event.inaxes != self.selected_point['ax']:
            return
        new_j_ma = event.xdata
        new_V = event.ydata
        if new_j_ma is not None and new_V is not None:
            self.update_dragged_point(new_j_ma, new_V)

    def on_plot_release(self, event):
        if not self.interaction_enabled or not self.edit_mode or not self.dragging:
            return

        self.dragging = False

        if self.selected_point is None:
            return

        new_j_ma = event.xdata
        new_V = event.ydata

        if new_j_ma is not None and new_V is not None and new_j_ma > 0:
            self.save_state()

            gkey, ckey = self._display_to_key(self.selected_point['group'])
            index = self.selected_point['index']
            new_j_A = new_j_ma / 1000

            if ckey is not None:
                data_df = self.groups[gkey]['curves'][ckey]['data']
            else:
                data_df = self.groups[gkey]['averaged_data']

            data_df.loc[index, 'j'] = new_j_A
            data_df.loc[index, 'V'] = new_V

            self.interaction_status.setText(f"Modified point: j={new_j_ma:.2f} mA/cm², V={new_V:.3f} V")
            self.load_status.setText("✓ Data modified - changes will be included in exports")
            self.update_plot()
            print(f"EDIT Point modified: j={new_j_ma:.2f} mA/cm², V={new_V:.3f} V")

    def update_dragged_point(self, new_j_ma, new_V):
        pass

    def show_point_info(self, point_info):
        annotation_text = (
            f"{point_info['name']}\n"
            f"j = {point_info['j_ma']:.2f} mA/cm²\n"
            f"I = {point_info['I']*1000:.2f} mA\n"
            f"V = {point_info['V']:.3f} V"
        )
        if self.edit_mode:
            annotation_text += "\n(Drag to edit)"

        self.selected_annotation = point_info['ax'].annotate(
            annotation_text,
            xy=(point_info['j_ma'], point_info['V']),
            xytext=(20, 20), textcoords='offset points',
            bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8),
            arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3', color='black', lw=1.5),
            fontsize=9, fontweight='bold'
        )

        if self.selected_highlight is not None:
            try:
                self.selected_highlight.remove()
            except Exception:
                pass
            self.selected_highlight = None

        self.selected_highlight = point_info['ax'].plot(
            point_info['j_ma'], point_info['V'], 'ro',
            markersize=10, markerfacecolor='none', markeredgewidth=2
        )[0]

        status_text = f"Selected: {point_info['name']} - j={point_info['j_ma']:.2f} mA/cm², V={point_info['V']:.3f} V"
        if self.edit_mode:
            status_text += " (Drag to edit)"
        self.interaction_status.setText(status_text)

        self.canvas.draw_idle()

    # ===================================================================
    # CSV EXPORT
    # ===================================================================

    def export_csv_data(self):
        flat = self._build_flat_groups()
        if not flat:
            QMessageBox.warning(self, "No Data", "Please load and analyze data before exporting")
            return

        dialog = CSVExportDialog(self, flat)
        if dialog.exec_() != QDialog.Accepted:
            return

        settings = dialog.get_export_settings()

        if not settings['groups']:
            QMessageBox.warning(self, "No Groups Selected", "Please select at least one group to export")
            return

        if settings['separate_files']:
            folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
            if not folder:
                return
            export_folder = Path(folder)
            single_filename = None
        else:
            default_name = "polarization_curves.csv" if settings['data_type'] == 'polarization' else "transient_data.csv"
            filepath, _ = QFileDialog.getSaveFileName(self, "Save CSV File", default_name, "CSV Files (*.csv);;All Files (*)")
            if not filepath:
                return
            export_folder = Path(filepath).parent
            single_filename = Path(filepath).name

        try:
            if settings['data_type'] == 'polarization':
                exported_files = self.export_polarization_csv(settings, export_folder, single_filename, flat)
            else:
                exported_files = self.export_transient_csv(settings, export_folder, single_filename, flat)

            if len(exported_files) == 1:
                QMessageBox.information(self, "Export Successful", f"Data exported to:\n{exported_files[0]}")
            else:
                file_list = '\n'.join([f"• {f.name}" for f in exported_files])
                QMessageBox.information(self, "Export Successful", f"Data exported to {len(exported_files)} files:\n\n{file_list}")

            self.load_status.setText(f"✓ Data exported to {len(exported_files)} CSV file(s)")

        except Exception as e:
            QMessageBox.critical(self, "Export Failed", f"Error exporting data:\n{str(e)}")

    def _build_flat_groups(self):
        """Build {gdisplay: {data, steps}} for the export dialog — one entry per group."""
        flat = {}
        for gkey, gdata in self.groups.items():
            gdisplay = self.group_display_names.get(gkey, gkey)
            if gdata['averaged_data'] is not None:
                flat[gdisplay] = {'data': gdata['averaged_data'], 'steps': None}
            else:
                for ckey, cdata in gdata['curves'].items():
                    if cdata['data'] is not None:
                        flat[gdisplay] = cdata
                        break
        return flat

    def _build_group_section(self, data, group_name, curve_name, area):
        """Build one export DataFrame section with the standard column layout."""
        df = data.copy()
        n = int(df['N_curves'].iloc[0]) if 'N_curves' in df.columns else 1
        i_mean = df['I_mean'] if 'I_mean' in df.columns else df['j'] * area
        return pd.DataFrame({
            'j (mA/cm2)':           df['j'] * 1000,
            'j (A/cm2)':            df['j'],
            'I (mA)':               i_mean * 1000,
            'I (A)':                i_mean,
            'V':                    df['V'],
            'V_uncertainty':        df['V_std'] if 'V_std' in df.columns else np.nan,
            'electrode_area (cm2)': area,
            'N_curves':             n,
            'Group':                group_name,
            'curve':                curve_name,
        })

    def _write_sections(self, sections, filepath):
        """Write a list of DataFrames to filepath with a blank line between each section."""
        with open(filepath, 'w', newline='') as f:
            for i, section in enumerate(sections):
                section.to_csv(f, index=False, header=(i == 0))
                f.write('\n')

    def export_polarization_csv(self, settings, export_folder, single_filename=None, flat=None):
        try:
            area = float(self.area_input.text())
        except (ValueError, AttributeError):
            area = 1.0

        # Map group display name -> gkey
        display_to_gkey = {
            self.group_display_names.get(gk, gk): gk
            for gk in self.groups
        }

        exported_files = []

        def sections_for_group(gdisplay):
            gkey = display_to_gkey.get(gdisplay)
            if gkey is None:
                return []
            gdata = self.groups[gkey]
            secs = []

            # Averaged section first
            if gdata['averaged_data'] is not None:
                secs.append(self._build_group_section(
                    gdata['averaged_data'], gdisplay, 'averaged', area
                ))

            # Then individual curves
            for ckey, cdata in gdata['curves'].items():
                if cdata['data'] is not None:
                    cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
                    secs.append(self._build_group_section(
                        cdata['data'], gdisplay, cdisplay, area
                    ))
            return secs

        if settings['separate_files']:
            for gdisplay in settings['groups']:
                secs = sections_for_group(gdisplay)
                if not secs:
                    continue
                safe = "".join(c for c in gdisplay if c.isalnum() or c in (' ', '-', '_')).strip()
                filepath = export_folder / f"polarization_{safe}.csv"
                self._write_sections(secs, filepath)
                exported_files.append(filepath)
        else:
            all_sections = []
            for gdisplay in settings['groups']:
                all_sections.extend(sections_for_group(gdisplay))
            if all_sections:
                filepath = export_folder / single_filename
                self._write_sections(all_sections, filepath)
                exported_files.append(filepath)

        return exported_files

    def export_transient_csv(self, settings, export_folder, single_filename=None, flat=None):
        if flat is None:
            flat = self._build_flat_groups()
        exported_files = []

        def collect_transient(group_name, group):
            rows = []
            steps = group.get('steps')
            if not steps:
                return rows
            for fname, file_steps in steps.items():
                for step_idx, step in enumerate(file_steps, 1):
                    df = pd.DataFrame({
                        'time': step['time'],
                        'time_rel': step['time_rel'],
                        'voltage': step['voltage'],
                        'current': step['current'],
                        'current_mA': step['current'] * 1000,
                        'file': fname,
                        'step': step_idx,
                        'group': group_name
                    })
                    rows.append(df)
            return rows

        if settings['separate_files']:
            for group_name in settings['groups']:
                group = flat.get(group_name)
                if group is None:
                    continue
                rows = collect_transient(group_name, group)
                if not rows:
                    continue
                combined = pd.concat(rows, ignore_index=True)
                safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filepath = export_folder / f"transient_{safe_name}.csv"
                combined.to_csv(filepath, index=False)
                exported_files.append(filepath)
        else:
            all_rows = []
            for group_name in settings['groups']:
                group = flat.get(group_name)
                if group is None:
                    continue
                all_rows.extend(collect_transient(group_name, group))
            if all_rows:
                combined = pd.concat(all_rows, ignore_index=True)
                filepath = export_folder / single_filename
                combined.to_csv(filepath, index=False)
                exported_files.append(filepath)

        return exported_files

    # ===================================================================
    # EXPORT PLOT
    # ===================================================================

    def export_plot(self):
        visible_groups = self.get_visible_groups()
        if not visible_groups:
            QMessageBox.warning(self, "No Data", "Please load and display data before exporting")
            return

        dialog = ExportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            settings = dialog.get_settings()
            file_filter = f"{settings['format'].upper()} Files (*.{settings['format']})"
            filepath, _ = QFileDialog.getSaveFileName(
                self, "Save Plot",
                f"polarization_curve.{settings['format']}",
                file_filter
            )

            if filepath:
                try:
                    original_size = self.fig.get_size_inches()
                    self.fig.set_size_inches(settings['width'], settings['height'])
                    self.fig.savefig(filepath, dpi=settings['dpi'], format=settings['format'],
                                     bbox_inches='tight', facecolor='white')
                    self.fig.set_size_inches(original_size)
                    self.canvas.draw()
                    QMessageBox.information(self, "Export Successful", f"Plot saved to:\n{filepath}")
                except Exception as e:
                    QMessageBox.critical(self, "Export Failed", f"Error saving plot:\n{str(e)}")

    # ===================================================================
    # PLOTTING
    # ===================================================================

    def update_plot(self):
        self.fig.clear()
        self.transient_highlights.clear()
        self.point_artists.clear()
        self.selected_annotation = None
        self.selected_highlight = None

        visible_groups = self.get_visible_groups()

        if not visible_groups:
            self.empty_plot()
            return

        if self.radio_with_transient.isChecked():
            # Filter out groups without step data (e.g., averaged curves)
            transient_groups = [
                (n, g, c) for n, g, c in visible_groups
                if self._label_to_source.get(n, (None,))[0] == self.active_group
                and g.get('steps') is not None
                and n not in self._source_curve_labels
            ] if self.active_group else []

            if not transient_groups:
                # All visible groups are averaged — fall back to polarization only
                self.plot_polarization_overlay(visible_groups)
            elif len(transient_groups) == 1:
                # Show the one transient group, plus overlay all polarization
                self.plot_single_with_transient(transient_groups[0], all_groups=visible_groups)
            else:
                self.plot_multi_with_transient(transient_groups, all_groups=visible_groups)
        else:
            if self.radio_grid.isChecked() and len(visible_groups) > 1:
                self.plot_polarization_grid(visible_groups)
            else:
                self.plot_polarization_overlay(visible_groups)

        try:
            self.fig.subplots_adjust(left=0.1, right=0.88, top=0.95, bottom=0.08)
        except Exception:
            pass

        self.canvas.draw()

    def _display_to_key(self, label):
        """Return (gkey, ckey_or_None) for a plot label"""
        return self._label_to_source.get(label, (label, None))

    def _shade_color(self, base_color, shade_idx, total):
        """Return a lighter shade of base_color for source curves."""
        if total <= 1:
            return base_color
        r, g, b, a = base_color
        factor = 0.4 + 0.5 * (shade_idx / max(total - 1, 1))
        return (r * factor + (1 - factor), g * factor + (1 - factor), b * factor + (1 - factor), a)

    def _current_mode(self):
        """Return True when area==0 (display current [A] instead of current density [mA/cm²])."""
        try:
            return float(self.area_input.text()) == 0.0
        except ValueError:
            return False

    def _x_values(self, data):
        """Return x-axis values for a polarization DataFrame."""
        if self._current_mode():
            return data['I_mean'].values
        return data['j'].values * 1000

    def _x_label(self):
        if self._current_mode():
            return 'Current [A]'
        return 'Current Density [mA/cm²]'

    def _x_label_short(self):
        if self._current_mode():
            return 'I [A]'
        return 'j [mA/cm²]'

    def get_visible_groups(self):
        """Return list of (plot_label, {data, steps}, color) for checked groups with data"""
        visible = []
        self._label_to_source = {}
        self._source_curve_labels = set()
        group_index = 0

        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            if not item or item.checkState() != Qt.Checked:
                continue

            gkey = item.data(Qt.UserRole) or item.text()
            if gkey not in self.groups:
                continue

            gdata = self.groups[gkey]
            gdisplay = self.group_display_names.get(gkey, gkey)
            base_color = self.colors[group_index % len(self.colors)]
            group_index += 1

            if gdata['averaged_data'] is not None:
                label = gdisplay
                self._label_to_source[label] = (gkey, None)
                visible.append((label, {'data': gdata['averaged_data'], 'steps': None}, base_color))

                if self.show_source_curves_cb.isChecked():
                    source_curves = [(ckey, cdata) for ckey, cdata in gdata['curves'].items()
                                     if cdata['data'] is not None]
                    total = len(source_curves)
                    for shade_idx, (ckey, cdata) in enumerate(source_curves):
                        cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
                        src_label = f"{gdisplay} / {cdisplay}"
                        self._label_to_source[src_label] = (gkey, ckey)
                        src_color = self._shade_color(base_color, shade_idx, total)
                        self._source_curve_labels.add(src_label)
                        visible.append((src_label, cdata, src_color))
            else:
                curves_with_data = [(ckey, cdata) for ckey, cdata in gdata['curves'].items()
                                    if cdata['data'] is not None]
                total = len(curves_with_data)
                for shade_idx, (ckey, cdata) in enumerate(curves_with_data):
                    cdisplay = self.curve_display_names.get(gkey, {}).get(ckey, ckey)
                    label = f"{gdisplay} / {cdisplay}"
                    self._label_to_source[label] = (gkey, ckey)
                    color = self._shade_color(base_color, shade_idx, total)
                    visible.append((label, cdata, color))

        return visible

    def plot_polarization_overlay(self, groups):
        ax = self.fig.add_subplot(111)

        for name, group, color in groups:
            data = group['data']
            x = self._x_values(data)
            is_source = name in self._source_curve_labels
            linestyle = '--' if is_source else '-'
            alpha = 0.4 if is_source else 1.0
            lw = 1.5 if is_source else 2

            has_errors = (
                'V_std' in data.columns
                and data['V_std'].notna().any()
                and data['V_std'].gt(0).any()
            )

            if has_errors and not is_source:
                container = ax.errorbar(
                    x, data['V'], yerr=data['V_std'],
                    marker='o', linestyle=linestyle, color=color,
                    label=name, markersize=6, linewidth=lw,
                    capsize=4, capthick=1.5, elinewidth=1.5, alpha=alpha,
                )
                line = container.lines[0]
            else:
                line, = ax.plot(x, data['V'], marker='o', linestyle=linestyle,
                                color=color, label=name, markersize=6, linewidth=lw,
                                alpha=alpha)

            if self.interaction_enabled:
                self.point_artists[name] = line

        ax.set_xlabel(self._x_label(), fontsize=16, fontweight='bold')
        ax.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
        ax.tick_params(axis='both', labelsize=14)
        ax.set_title('Polarization Curves', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.legend(fontsize=14, loc='best', framealpha=0.9)

    def plot_polarization_grid(self, groups):
        n = len(groups)
        cols = min(2, n)
        rows = (n + cols - 1) // cols

        for i, (name, group, color) in enumerate(groups):
            ax = self.fig.add_subplot(rows, cols, i + 1)
            data = group['data']
            x = self._x_values(data)

            has_errors = (
                'V_std' in data.columns
                and data['V_std'].notna().any()
                and data['V_std'].gt(0).any()
            )

            if has_errors:
                container = ax.errorbar(
                    x, data['V'], yerr=data['V_std'],
                    marker='o', linestyle='-', color=color,
                    markersize=5, linewidth=1.5, capsize=4, capthick=1.5, elinewidth=1.5,
                )
                line = container.lines[0]
            else:
                line, = ax.plot(x, data['V'], marker='o', linestyle='-',
                                color=color, markersize=5, linewidth=1.5)
            ax.set_title(name, fontsize=14, fontweight='bold')

            if self.interaction_enabled:
                self.point_artists[f"{name}_{i}"] = line

            ax.set_xlabel(self._x_label_short(), fontsize=16)
            ax.set_ylabel('V [V]', fontsize=16)
            ax.tick_params(axis='both', labelsize=14)
            ax.grid(True, alpha=0.3, linestyle='--')

    def plot_single_with_transient(self, group_tuple, all_groups=None):
        name, group, group_color = group_tuple
        data = group['data']
        steps = group['steps']

        gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1.5], hspace=0.3)
        ax1 = self.fig.add_subplot(gs[0])
        ax2 = self.fig.add_subplot(gs[1])

        # Top: all visible polarization curves
        plot_groups = all_groups if all_groups else [group_tuple]
        for pname, pgroup, pcolor in plot_groups:
            pdata = pgroup['data']
            x = self._x_values(pdata)
            is_source = pname in self._source_curve_labels
            linestyle = '--' if is_source else '-'
            alpha = 0.4 if is_source else 1.0
            lw = 1.5 if is_source else 2

            has_errors = (
                'V_std' in pdata.columns
                and pdata['V_std'].notna().any()
                and pdata['V_std'].gt(0).any()
            )

            if has_errors and not is_source:
                container = ax1.errorbar(
                    x, pdata['V'], yerr=pdata['V_std'],
                    marker='o', linestyle=linestyle, color=pcolor,
                    label=pname, markersize=7, linewidth=lw,
                    capsize=4, capthick=1.5, elinewidth=1.5, alpha=alpha,
                )
                line = container.lines[0]
            else:
                line, = ax1.plot(x, pdata['V'], marker='o', linestyle=linestyle,
                                 color=pcolor, label=pname, markersize=7, linewidth=lw,
                                 alpha=alpha)

            if self.interaction_enabled:
                self.point_artists[pname] = line

        ax1.set_xlabel(self._x_label(), fontsize=16, fontweight='bold')
        ax1.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
        ax1.tick_params(axis='both', labelsize=14)
        ax1.set_title('Polarization Curves', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, linestyle='--')
        if len(plot_groups) > 1:
            ax1.legend(fontsize=14, loc='best', framealpha=0.9)

        # Bottom: transients for the single group with step data
        ax2_voltage = ax2
        ax2_current = ax2.twinx()

        color = group_color
        time_offset = 0
        previous_current = None

        for filename in sorted(steps.keys()):
            file_steps = steps[filename]
            for step_idx, step in enumerate(file_steps):
                t = step['time_rel'] + time_offset
                V = step['voltage']
                current_mean = step['I_mean']

                ax2_voltage.plot(t, V, 'o', markersize=4, alpha=0.8, color=color,
                                 label='Voltage' if time_offset == 0 else "")
                ax2_current.hlines(current_mean * 1000, t[0], t[-1],
                                   colors='gray', linestyles='--', linewidth=2, alpha=0.7,
                                   label='Current' if time_offset == 0 else "")

                if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                    ax2_voltage.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                previous_current = current_mean

                matching = data[
                    (data['file'] == filename) &
                    (np.isclose(data['I_mean'], step['I_mean'], rtol=0.01))
                ]

                if len(matching) > 0:
                    row = matching.iloc[0]
                    ss_start = row['steady_start']
                    ss_mask = step['time_rel'] >= ss_start
                    t_ss = step['time_rel'][ss_mask] + time_offset
                    V_ss = step['voltage'][ss_mask]

                    if len(V_ss) > 0:
                        ax2_voltage.fill_between(
                            t_ss, V_ss.min() - 0.01, V_ss.max() + 0.01,
                            alpha=0.3, color='yellow',
                            label='Steady-state region' if time_offset == 0 else ""
                        )
                        ax2_voltage.plot(
                            [t_ss[0], t_ss[-1]], [row['V'], row['V']],
                            'r--', linewidth=2, alpha=0.7,
                            label='Average voltage' if time_offset == 0 else ""
                        )

                time_offset = t[-1]

        ax2_voltage.set_xlabel('Time [s]', fontsize=16, fontweight='bold')
        ax2_voltage.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold', color='black')
        ax2_voltage.tick_params(axis='y', labelcolor='black')
        ax2_current.set_ylabel('Current [mA]', fontsize=16, fontweight='bold', color='gray')
        ax2_current.tick_params(axis='y', labelcolor='gray')
        ax2_voltage.set_title(f'Voltage Transients - {name}', fontsize=16, fontweight='bold')
        ax2_voltage.grid(True, alpha=0.3, linestyle='--')

        lines1, labels1 = ax2_voltage.get_legend_handles_labels()
        lines2, labels2 = ax2_current.get_legend_handles_labels()
        by_label = dict(zip(labels1 + labels2, lines1 + lines2))
        extras = ['Steady-state region', 'Average voltage', 'Current']
        ordered = [k for k in by_label if k not in extras] + [k for k in extras if k in by_label]
        ax2_voltage.legend([by_label[k] for k in ordered], ordered, fontsize=14, loc='best', framealpha=0.9)

    def plot_multi_with_transient(self, groups, all_groups=None):
        n = len(groups)
        overlay_mode = self.radio_overlay.isChecked()

        if overlay_mode:
            gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1.5], hspace=0.3)
            ax1 = self.fig.add_subplot(gs[0])
            ax2 = self.fig.add_subplot(gs[1])
            ax2_current = ax2.twinx()

            # Plot all polarization curves (including averaged ones)
            plot_groups = all_groups if all_groups else groups
            for pname, pgroup, pcolor in plot_groups:
                pdata = pgroup['data']
                x = self._x_values(pdata)
                is_source = pname in self._source_curve_labels
                linestyle = '--' if is_source else '-'
                alpha = 0.4 if is_source else 1.0
                lw = 1.5 if is_source else 2
                line, = ax1.plot(x, pdata['V'], 'o', linestyle=linestyle,
                                 color=pcolor, label=pname,
                                 markersize=6, linewidth=lw, alpha=alpha)
                if self.interaction_enabled:
                    self.point_artists[pname] = line

            ax1.set_xlabel(self._x_label(), fontsize=16, fontweight='bold')
            ax1.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
            ax1.tick_params(axis='both', labelsize=14)
            ax1.set_title('Polarization Curves', fontsize=14, fontweight='bold')
            ax1.legend(fontsize=14, loc='best', framealpha=0.9)
            ax1.grid(True, alpha=0.3, linestyle='--')

            for i, (name, group, color) in enumerate(groups):
                data = group['data']
                steps = group['steps']

                time_offset = 0
                previous_current = None

                for filename in sorted(steps.keys()):
                    for step in steps[filename]:
                        t = step['time_rel'] + time_offset
                        current_mean = step['I_mean']

                        ax2.plot(t, step['voltage'], 'o', color=color, markersize=4, alpha=0.8,
                                 label=name if time_offset == 0 else "")

                        if i == 0:
                            ax2_current.hlines(current_mean * 1000, t[0], t[-1],
                                               colors='gray', linestyles='--', linewidth=2, alpha=0.7,
                                               label='Current' if time_offset == 0 and i == 0 else "")

                        if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                            ax2.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                        previous_current = current_mean

                        matching = data[
                            (data['file'] == filename) &
                            (np.isclose(data['I_mean'], step['I_mean'], rtol=0.01))
                        ]

                        if len(matching) > 0:
                            row = matching.iloc[0]
                            ss_mask = step['time_rel'] >= row['steady_start']
                            t_ss = step['time_rel'][ss_mask] + time_offset
                            V_ss = step['voltage'][ss_mask]
                            if len(V_ss) > 0:
                                ax2.fill_between(t_ss, V_ss.min() - 0.01, V_ss.max() + 0.01,
                                                 alpha=0.3, color='yellow',
                                                 label='Steady-state' if time_offset == 0 and i == 0 else "")
                                ax2.plot([t_ss[0], t_ss[-1]], [row['V'], row['V']],
                                         'r--', linewidth=2, alpha=0.7,
                                         label='Avg voltage' if time_offset == 0 and i == 0 else "")

                        time_offset = t[-1]

            ax2.set_xlabel('Time [s]', fontsize=11, fontweight='bold')
            ax2.set_ylabel('Voltage [V]', fontsize=11, fontweight='bold', color='black')
            ax2.tick_params(axis='y', labelcolor='black')
            ax2_current.set_ylabel('Current [mA]', fontsize=11, fontweight='bold', color='gray')
            ax2_current.tick_params(axis='y', labelcolor='gray')
            ax2.set_title('Voltage Transients', fontsize=13, fontweight='bold')
            ax2.grid(True, alpha=0.3, linestyle='--')

            lines1, labels1 = ax2.get_legend_handles_labels()
            lines2, labels2 = ax2_current.get_legend_handles_labels()
            by_label = dict(zip(labels1 + labels2, lines1 + lines2))
            extras = ['Steady-state', 'Avg voltage', 'Current']
            ordered = [k for k in by_label if k not in extras] + [k for k in extras if k in by_label]
            ax2.legend([by_label[k] for k in ordered], ordered, fontsize=14, loc='best', framealpha=0.9)

        else:
            for i, (name, group, color) in enumerate(groups):
                data = group['data']
                steps = group['steps']
                x = self._x_values(data)

                ax1 = self.fig.add_subplot(n, 2, 2*i + 1)
                line, = ax1.plot(x, data['V'], 'o', color=color)
                if self.interaction_enabled:
                    self.point_artists[f"{name}_polar"] = line
                ax1.set_title(f'{name} - Polarization', fontsize=10, fontweight='bold')
                ax1.set_xlabel(self._x_label_short(), fontsize=9)
                ax1.set_ylabel('V [V]', fontsize=9)
                ax1.grid(True, alpha=0.3)

                ax2 = self.fig.add_subplot(n, 2, 2*i + 2)
                ax2_current = ax2.twinx()

                time_offset = 0
                previous_current = None

                for filename in sorted(steps.keys()):
                    for step in steps[filename]:
                        t = step['time_rel'] + time_offset
                        current_mean = step['I_mean']

                        ax2.plot(t, step['voltage'], 'o', color=color, markersize=3, alpha=0.7)
                        ax2_current.hlines(current_mean * 1000, t[0], t[-1],
                                           colors='gray', linestyles='--', linewidth=1.5, alpha=0.7)

                        if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                            ax2.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                        previous_current = current_mean

                        matching = data[
                            (data['file'] == filename) &
                            (np.isclose(data['I_mean'], step['I_mean'], rtol=0.01))
                        ]

                        if len(matching) > 0:
                            row = matching.iloc[0]
                            ss_mask = step['time_rel'] >= row['steady_start']
                            t_ss = step['time_rel'][ss_mask] + time_offset
                            V_ss = step['voltage'][ss_mask]
                            if len(V_ss) > 0:
                                ax2.fill_between(t_ss, V_ss.min() - 0.01, V_ss.max() + 0.01,
                                                 alpha=0.3, color='yellow')
                                ax2.plot([t_ss[0], t_ss[-1]], [row['V'], row['V']],
                                         'r--', linewidth=1.5, alpha=0.7)

                        time_offset = t[-1]

                ax2.set_title(f'{name} - Transients', fontsize=10, fontweight='bold')
                ax2.set_xlabel('Time [s]', fontsize=9)
                ax2.set_ylabel('V [V]', fontsize=9, color='black')
                ax2.tick_params(axis='y', labelcolor='black')
                ax2_current.set_ylabel('I [mA]', fontsize=9, color='gray')
                ax2_current.tick_params(axis='y', labelcolor='gray')
                ax2.grid(True, alpha=0.3)

    def empty_plot(self):
        self.fig.clear()
        ax = self.fig.add_subplot(111)

        instructions = (
            "Polarization Curve Analysis\n\n"
            "Getting Started:\n"
            "1. Click '+ New Group' to create a group\n"
            "2. Click '+ New Curve' to create a curve in the group\n"
            "3. Click 'Load Folder into Curve' to load data\n\n"
            "The app will automatically:\n"
            "- Detect current steps\n"
            "- Extract steady-state voltages\n"
            "- Build polarization curve\n\n"
            "Groups can contain multiple curves.\n"
            "Use 'Average Curves' to average curves within a group."
        )

        ax.text(0.5, 0.5, instructions, ha='center', va='center',
                fontsize=11, color='gray', transform=ax.transAxes)
        ax.axis('off')
        self.canvas.draw()


class ExportDialog(QDialog):
    """Dialog for customizing plot export settings"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Plot Settings")
        self.setModal(True)

        layout = QVBoxLayout(self)

        size_group = QGroupBox("Plot Size (inches)")
        size_layout = QVBoxLayout()
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(4, 24)
        self.width_spin.setValue(10)
        self.width_spin.setSuffix(" in")
        width_layout.addWidget(self.width_spin)
        size_layout.addLayout(width_layout)
        height_layout = QHBoxLayout()
        height_layout.addWidget(QLabel("Height:"))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(4, 24)
        self.height_spin.setValue(8)
        self.height_spin.setSuffix(" in")
        height_layout.addWidget(self.height_spin)
        size_layout.addLayout(height_layout)
        size_group.setLayout(size_layout)
        layout.addWidget(size_group)

        dpi_group = QGroupBox("Resolution (DPI)")
        dpi_layout = QHBoxLayout()
        dpi_layout.addWidget(QLabel("DPI:"))
        self.dpi_combo = QComboBox()
        self.dpi_combo.addItems(['150', '300', '600', '1200'])
        self.dpi_combo.setCurrentText('300')
        self.dpi_combo.setEditable(True)
        dpi_layout.addWidget(self.dpi_combo)
        dpi_group.setLayout(dpi_layout)
        layout.addWidget(dpi_group)

        format_group = QGroupBox("File Format")
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['png', 'pdf', 'svg', 'jpg', 'tiff'])
        self.format_combo.setCurrentText('png')
        format_layout.addWidget(self.format_combo)
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)

        preset_layout = QHBoxLayout()
        paper_btn = QPushButton("Paper (8×6)")
        paper_btn.clicked.connect(lambda: self.apply_preset(8, 6))
        preset_layout.addWidget(paper_btn)
        presentation_btn = QPushButton("Presentation (12×8)")
        presentation_btn.clicked.connect(lambda: self.apply_preset(12, 8))
        preset_layout.addWidget(presentation_btn)
        poster_btn = QPushButton("Poster (16×12)")
        poster_btn.clicked.connect(lambda: self.apply_preset(16, 12))
        preset_layout.addWidget(poster_btn)
        layout.addLayout(preset_layout)

        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Export")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)

    def apply_preset(self, width, height):
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)

    def get_settings(self):
        return {
            'width': self.width_spin.value(),
            'height': self.height_spin.value(),
            'dpi': int(self.dpi_combo.currentText()),
            'format': self.format_combo.currentText()
        }
