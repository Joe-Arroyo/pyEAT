"""
Polarization Curves analysis tab
Chronopotentiometry (Gamry) → Polarization curves
BUILT FROM SCRATCH - WORKING VERSION
Enhanced with interaction controls and CSV export options
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
plt.rcParams['legend.fontsize'] = 14  # Match polarization curve legends
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
        
        # Data type selection
        type_group = QGroupBox("Data Type")
        type_layout = QVBoxLayout()
        
        self.polar_radio = QRadioButton("Polarization Curves (processed data)")
        self.transient_radio = QRadioButton("Transient Data (raw time series)")
        self.polar_radio.setChecked(True)
        
        type_layout.addWidget(self.polar_radio)
        type_layout.addWidget(self.transient_radio)
        type_group.setLayout(type_layout)
        layout.addWidget(type_group)
        
        # Group selection
        group_group = QGroupBox("Groups to Export")
        group_layout = QVBoxLayout()
        
        self.group_checkboxes = {}
        if self.groups:
            for group_name, group_data in self.groups.items():
                if group_data['data'] is not None:  # Only show groups with data
                    checkbox = QCheckBox(group_name)
                    checkbox.setChecked(True)
                    self.group_checkboxes[group_name] = checkbox
                    group_layout.addWidget(checkbox)
        
        if not self.group_checkboxes:
            no_data_label = QLabel("No groups with data available")
            no_data_label.setStyleSheet("color: gray; font-style: italic;")
            group_layout.addWidget(no_data_label)
        
        group_group.setLayout(group_layout)
        layout.addWidget(group_group)
        
        # File format options
        format_group = QGroupBox("Format Options")
        format_layout = QVBoxLayout()
        
        self.include_metadata = QCheckBox("Include metadata (electrode area, processing settings)")
        self.include_metadata.setChecked(True)
        format_layout.addWidget(self.include_metadata)
        
        self.separate_files = QCheckBox("Separate file per group")
        self.separate_files.setChecked(False)
        format_layout.addWidget(self.separate_files)
        
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Export")
        ok_btn.clicked.connect(self.accept)
        ok_btn.setEnabled(bool(self.group_checkboxes))  # Only enable if there are groups
        
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
    
    def get_export_settings(self):
        """Get export settings from dialog"""
        selected_groups = [name for name, checkbox in self.group_checkboxes.items() 
                          if checkbox.isChecked()]
        
        return {
            'data_type': 'polarization' if self.polar_radio.isChecked() else 'transient',
            'groups': selected_groups,
            'include_metadata': self.include_metadata.isChecked(),
            'separate_files': self.separate_files.isChecked()
        }


class PolarizationTab(QWidget):
    """
    Tab for analyzing chronopotentiometry data and building polarization curves.
    Supports multiple groups for comparison.
    """

    def __init__(self):
        super().__init__()
        
        # Data storage
        self.groups = {}  # {group_name: {files, data, steps}}
        self.active_group = None
        
        # Colors for plotting
        self.colors = plt.cm.tab10(np.linspace(0, 1, 10))
        
        # Point manipulation system
        self.interaction_enabled = False  # NEW: Control interaction
        self.edit_mode = False
        self.selected_point = None  # {'group': name, 'index': idx, 'artist': plot_point}
        self.dragging = False
        self.drag_start_pos = None
        self.point_artists = {}  # Store matplotlib artist objects for each point
        
        # Undo/Redo system
        self.undo_stack = []  # List of data state snapshots
        self.redo_stack = []
        self.max_undo_levels = 50

        # Track highlighted regions in transient plot
        self.transient_highlights = []
        
        self.init_ui()
        self.setup_shortcuts()

    def setup_shortcuts(self):
        """Setup keyboard shortcuts for undo/redo"""
        # Ctrl+Z for undo
        self.undo_shortcut = QShortcut(QKeySequence("Ctrl+Z"), self)
        self.undo_shortcut.activated.connect(self.undo_action)
        
        # Ctrl+Y for redo
        self.redo_shortcut = QShortcut(QKeySequence("Ctrl+Y"), self)
        self.redo_shortcut.activated.connect(self.redo_action)

    def save_state(self):
        """Save current state to undo stack"""
        # Deep copy of all group data
        state = {}
        for group_name, group_data in self.groups.items():
            if group_data['data'] is not None:
                state[group_name] = {
                    'data': group_data['data'].copy(),
                    'files': group_data['files'],  # Files don't change
                    'steps': group_data['steps']   # Steps don't change
                }
        
        self.undo_stack.append(state)
        
        # Limit undo stack size
        if len(self.undo_stack) > self.max_undo_levels:
            self.undo_stack.pop(0)
        
        # Clear redo stack when new action is performed
        self.redo_stack.clear()
        
        # Update button states
        self.update_undo_redo_buttons()

    def undo_action(self):
        """Undo last change"""
        if not self.undo_stack:
            return
        
        # Save current state to redo stack
        current_state = {}
        for group_name, group_data in self.groups.items():
            if group_data['data'] is not None:
                current_state[group_name] = {
                    'data': group_data['data'].copy(),
                    'files': group_data['files'],
                    'steps': group_data['steps']
                }
        self.redo_stack.append(current_state)
        
        # Restore previous state
        previous_state = self.undo_stack.pop()
        for group_name, group_data in previous_state.items():
            if group_name in self.groups:
                self.groups[group_name]['data'] = group_data['data'].copy()
        
        # Clear selection
        self.selected_point = None
        self.edit_mode = False
        if hasattr(self, 'edit_mode_btn'):
            self.edit_mode_btn.setChecked(False)
        
        # Update plot and buttons
        self.update_plot()
        self.update_undo_redo_buttons()
        if hasattr(self, 'load_status'):
            self.load_status.setText("✓ Undo completed")

    def redo_action(self):
        """Redo last undone change"""
        if not self.redo_stack:
            return
        
        # Save current state to undo stack
        current_state = {}
        for group_name, group_data in self.groups.items():
            if group_data['data'] is not None:
                current_state[group_name] = {
                    'data': group_data['data'].copy(),
                    'files': group_data['files'],
                    'steps': group_data['steps']
                }
        self.undo_stack.append(current_state)
        
        # Restore next state
        next_state = self.redo_stack.pop()
        for group_name, group_data in next_state.items():
            if group_name in self.groups:
                self.groups[group_name]['data'] = group_data['data'].copy()
        
        # Clear selection
        self.selected_point = None
        self.edit_mode = False
        if hasattr(self, 'edit_mode_btn'):
            self.edit_mode_btn.setChecked(False)
        
        # Update plot and buttons
        self.update_plot()
        self.update_undo_redo_buttons()
        if hasattr(self, 'load_status'):
            self.load_status.setText("✓ Redo completed")

    def update_undo_redo_buttons(self):
        """Update undo/redo button states"""
        if hasattr(self, 'undo_btn'):
            self.undo_btn.setEnabled(len(self.undo_stack) > 0)
        if hasattr(self, 'redo_btn'):
            self.redo_btn.setEnabled(len(self.redo_stack) > 0)

    # ===================================================================
    # UI INITIALIZATION
    # ===================================================================

    def init_ui(self):
        """Build the user interface"""
        main_layout = QHBoxLayout(self)
        
        # Left panel (controls)
        left_panel = self.create_left_panel()
        
        # Right panel (plot)
        right_panel = self.create_right_panel()
        
        main_layout.addWidget(left_panel)
        main_layout.addWidget(right_panel)
        
        self.empty_plot()

    def create_left_panel(self):
        """Create the left control panel"""
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumWidth(480)  # Standardized width
        
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # Group management section (moved to top)
        layout.addWidget(self.create_group_section())
        
        # File loading section (moved below groups)
        layout.addWidget(self.create_load_section())
        
        # Processing parameters section
        layout.addWidget(self.create_processing_section())
        
        # Data interaction section - NEW
        layout.addWidget(self.create_interaction_section())
        
        # Plot options section
        layout.addWidget(self.create_plot_section())
        
        # Export section - ENHANCED
        layout.addWidget(self.create_export_section())
        
        layout.addStretch()
        
        scroll.setWidget(container)
        return scroll

    def create_load_section(self):
        """Create file loading section"""
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

        self.load_btn = QPushButton("Load Folder into Group")
        self.load_btn.clicked.connect(self.load_folder)
        layout.addWidget(self.load_btn)

        # Single file loading (useful for Riden)
        self.load_file_btn = QPushButton("Load Single File into Group")
        self.load_file_btn.clicked.connect(self.load_single_file)
        layout.addWidget(self.load_file_btn)
        
        self.load_status = QLabel("No data loaded")
        self.load_status.setWordWrap(True)
        self.load_status.setStyleSheet("color: gray;")
        layout.addWidget(self.load_status)
        
        box.setLayout(layout)
        return box

    def create_group_section(self):
        """Create group management section"""
        box = QGroupBox("🏷️ Groups")
        layout = QVBoxLayout()
        
        self.group_list = QListWidget()
        self.group_list.itemChanged.connect(self.on_group_checkbox_changed)
        self.group_list.currentItemChanged.connect(self.on_group_selected)
        self.group_list.itemDoubleClicked.connect(self.rename_group)
        layout.addWidget(self.group_list)
        
        btn_layout = QHBoxLayout()
        self.new_group_btn = QPushButton("+ New")
        self.new_group_btn.clicked.connect(self.create_new_group)
        btn_layout.addWidget(self.new_group_btn)
        
        self.rename_group_btn = QPushButton("Rename")
        self.rename_group_btn.clicked.connect(self.rename_group)
        btn_layout.addWidget(self.rename_group_btn)
        
        self.del_group_btn = QPushButton("Remove")
        self.del_group_btn.clicked.connect(self.remove_group)
        btn_layout.addWidget(self.del_group_btn)
        
        layout.addLayout(btn_layout)
        
        self.group_status = QLabel("Create a group to start")
        self.group_status.setWordWrap(True)
        self.group_status.setStyleSheet("color: gray; font-size: 10px;")
        layout.addWidget(self.group_status)
        
        box.setLayout(layout)
        return box

    def create_processing_section(self):
        """Create processing parameters section"""
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
        
        # Update button
        self.update_btn = QPushButton("Update Analysis")
        self.update_btn.setToolTip("Recalculate polarization curves with new parameters")
        self.update_btn.clicked.connect(self.on_parameters_changed)
        layout.addWidget(self.update_btn)
        
        box.setLayout(layout)
        return box

    def create_interaction_section(self):
        """Create data interaction controls section - NEW"""
        box = QGroupBox("🎯 Data Interaction")
        layout = QVBoxLayout()
        
        # Enable interaction checkbox
        self.enable_interaction_cb = QCheckBox("Enable data interaction")
        self.enable_interaction_cb.setToolTip("Enable point selection and editing on plots")
        self.enable_interaction_cb.stateChanged.connect(self.toggle_interaction)
        layout.addWidget(self.enable_interaction_cb)
        
        # Edit mode controls (initially disabled)
        self.interaction_controls = QWidget()
        interaction_layout = QVBoxLayout(self.interaction_controls)
        interaction_layout.setContentsMargins(20, 5, 0, 5)  # Indent
        
        # Edit mode button
        self.edit_mode_btn = QPushButton("🔧 Enable Edit Mode")
        self.edit_mode_btn.setCheckable(True)
        self.edit_mode_btn.setToolTip("Click to edit data points by dragging")
        self.edit_mode_btn.clicked.connect(self.toggle_edit_mode)
        interaction_layout.addWidget(self.edit_mode_btn)
        
        # Undo/Redo buttons
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
        
        # Status label
        self.interaction_status = QLabel("Select a point to see details")
        self.interaction_status.setWordWrap(True)
        self.interaction_status.setStyleSheet("color: gray; font-size: 9px;")
        interaction_layout.addWidget(self.interaction_status)
        
        self.interaction_controls.setVisible(False)  # Hidden by default
        layout.addWidget(self.interaction_controls)
        
        box.setLayout(layout)
        return box

    def create_plot_section(self):
        """Create plot options section"""
        box = QGroupBox("📊 Plot Options")
        layout = QVBoxLayout()
        
        # Plot type radio buttons (group 1)
        layout.addWidget(QLabel("Plot type:"))
        self.plot_type_group = QButtonGroup(self)  # Group for mutual exclusivity
        self.radio_polar_only = QRadioButton("Polarization only")
        self.radio_with_transient = QRadioButton("With voltage transients")
        self.plot_type_group.addButton(self.radio_polar_only)
        self.plot_type_group.addButton(self.radio_with_transient)
        self.radio_polar_only.setChecked(True)
        self.radio_polar_only.toggled.connect(self.update_plot)
        self.radio_with_transient.toggled.connect(self.update_plot)
        layout.addWidget(self.radio_polar_only)
        layout.addWidget(self.radio_with_transient)
        
        # Multi-group layout radio buttons (group 2)
        layout.addWidget(QLabel("Multi-group layout:"))
        self.layout_type_group = QButtonGroup(self)  # Group for mutual exclusivity
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
        """Create export section - ENHANCED"""
        box = QGroupBox("💾 Export")
        layout = QVBoxLayout()
        
        # CSV export button - NEW
        self.export_csv_btn = QPushButton("Export Data as CSV...")
        self.export_csv_btn.setToolTip("Export polarization or transient data to CSV")
        self.export_csv_btn.clicked.connect(self.export_csv_data)
        self.export_csv_btn.setEnabled(False)
        layout.addWidget(self.export_csv_btn)
        
        # Plot export button
        self.export_plot_btn = QPushButton("Export Plot...")
        self.export_plot_btn.setToolTip("Export current plot with custom size and DPI")
        self.export_plot_btn.clicked.connect(self.export_plot)
        self.export_plot_btn.setEnabled(False)
        layout.addWidget(self.export_plot_btn)
        
        box.setLayout(layout)
        return box

    def create_right_panel(self):
        """Create the right panel with matplotlib plot"""
        container = QWidget()
        layout = QVBoxLayout(container)
        
        # Create matplotlib figure
        self.fig = Figure(figsize=(10, 8))
        self.canvas = FigureCanvas(self.fig)
        self.toolbar = NavigationToolbar(self.canvas, self)
        
        # Add click event for interactive point selection
        self.canvas.mpl_connect('button_press_event', self.on_plot_click)
        self.canvas.mpl_connect('button_release_event', self.on_plot_release)
        self.canvas.mpl_connect('motion_notify_event', self.on_plot_motion)
        
        self.selected_annotation = None  # Store annotation to update/remove
        
        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)
        
        return container

    # ===================================================================
    # INTERACTION CONTROLS - NEW/ENHANCED
    # ===================================================================

    def toggle_interaction(self, state):
        """Toggle data interaction on/off"""
        self.interaction_enabled = state == Qt.Checked
        self.interaction_controls.setVisible(self.interaction_enabled)
        
        if not self.interaction_enabled:
            # Clear any existing selection
            self.selected_point = None
            self.edit_mode = False
            self.edit_mode_btn.setChecked(False)
            self.clear_selection_visual()
            self.interaction_status.setText("Interaction disabled")
        else:
            self.interaction_status.setText("Select a point to see details")
        
        self.update_plot()

    def toggle_edit_mode(self, checked):
        """Toggle edit mode on/off"""
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
        """Highlight the corresponding current step in transient plot"""
        
        # Only works if showing transients
        if not self.radio_with_transient.isChecked():
            return
        
        # Clear previous highlights
        for artist in self.transient_highlights:
            try:
                artist.remove()
            except Exception:
                pass
        self.transient_highlights.clear()

        # Get selected point info
        group_name = selected_point['group']
        I_mean = selected_point['I']
        
        # Find transient voltage axis
        # The transient axis has:
        # - Title containing "Voltage Transients" OR
        # - X-axis labeled with "Time" (not "Current Density")
        transient_ax = None
        for ax in self.fig.get_axes():
            title = ax.get_title()
            xlabel = ax.get_xlabel()
            ylabel = ax.get_ylabel()
            
            # Check if this is the transient axis
            if 'Voltage Transients' in title:
                transient_ax = ax
                break
            elif 'Time' in xlabel and 'Voltage' in ylabel:
                transient_ax = ax
                break
        
        if transient_ax is None:
            return
        
        # Get group data
        if group_name not in self.groups:
            return
        
        group = self.groups[group_name]
        steps = group['steps']
        data = group['data']
        
        if not steps or data is None:
            return
        
        # Find matching step
        time_offset = 0
        found_step = False
        
        for filename in sorted(steps.keys()):
            file_steps = steps[filename]
            
            for step_idx, step in enumerate(file_steps):
                step_I_mean = step['I_mean']
                
                # Calculate time array for this step (needed for offset calculation)
                t = step['time_rel'] + time_offset
                
                # Check if this step matches (within 1%)
                if np.abs(step_I_mean - I_mean) / np.abs(I_mean) < 0.01:
                    V = step['voltage']
                    
                    # Highlight with orange box
                    highlight = transient_ax.axvspan(
                        t[0], t[-1],
                        alpha=0.3,
                        color='orange',
                        zorder=0
                    )
                    self.transient_highlights.append(highlight)
                    
                    # Add vertical line at start
                    vline = transient_ax.axvline(
                        t[0],
                        color='red',
                        linewidth=3,
                        linestyle='--',
                        alpha=0.8,
                        zorder=10
                    )
                    self.transient_highlights.append(vline)
                    
                    # Add text annotation
                    text_y = transient_ax.get_ylim()[1] * 0.95
                    text = transient_ax.text(
                        (t[0] + t[-1]) / 2,
                        text_y,
                        f'I = {I_mean*1000:.1f} mA',
                        ha='center',
                        va='top',
                        fontsize=10,
                        fontweight='bold',
                        color='red',
                        bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8)
                    )
                    self.transient_highlights.append(text)
                    
                    found_step = True
                    break
                
                # Update time offset for next step
                time_offset = t[-1] if len(step['time_rel']) > 0 else time_offset
            
            if found_step:
                break
        
        self.canvas.draw_idle()

    def clear_selection_visual(self):
        """Clear visual indicators of selection"""
        if self.selected_annotation is not None:
            try:
                self.selected_annotation.remove()
            except Exception:
                pass
            self.selected_annotation = None

        # Clear transient highlights
        for artist in self.transient_highlights:
            try:
                artist.remove()
            except Exception:
                pass
        self.transient_highlights.clear()

        # Remove any selection highlights
        for ax in self.fig.get_axes():
            # Remove any temporary highlight points
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
        """Create a new group for organizing data"""
        group_number = len(self.groups) + 1
        group_name = f"Group {group_number}"
        
        # Initialize group data structure
        self.groups[group_name] = {
            'files': {},      # {filename: ElectrolyzerData}
            'data': None,     # Polarization curve DataFrame
            'steps': None     # Step information for plotting
        }
        
        # Add to list widget
        item = QListWidgetItem(group_name)
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        self.group_list.addItem(item)
        
        # Set as active
        self.group_list.setCurrentItem(item)
        self.active_group = group_name
        
        self.group_status.setText(f"Active: {group_name}")
        self.update_export_buttons()
        print(f"OK Created {group_name}")

    def remove_group(self):
        """Remove the currently selected group"""
        item = self.group_list.currentItem()
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select a group to remove")
            return
        
        group_name = item.text()
        
        # Confirm deletion
        reply = QMessageBox.question(
            self, 
            "Confirm Deletion",
            f"Remove '{group_name}' and all its data?",
            QMessageBox.Yes | QMessageBox.No
        )
        
        if reply == QMessageBox.Yes:
            del self.groups[group_name]
            self.group_list.takeItem(self.group_list.row(item))
            
            if self.active_group == group_name:
                self.active_group = None
            
            self.update_export_buttons()
            self.update_plot()
            print(f"OK Removed {group_name}")

    def rename_group(self, item=None):
        """Rename the selected group"""
        if item is None:
            item = self.group_list.currentItem()
        
        if not item:
            QMessageBox.warning(self, "No Selection", "Please select a group to rename")
            return
        
        old_name = item.text()
        
        # Ask for new name
        new_name, ok = QInputDialog.getText(
            self,
            "Rename Group",
            "Enter new name:",
            text=old_name
        )
        
        if ok and new_name and new_name != old_name:
            # Check if name already exists
            if new_name in self.groups:
                QMessageBox.warning(
                    self,
                    "Name Exists",
                    f"A group named '{new_name}' already exists"
                )
                return
            
            # Update the groups dictionary
            self.groups[new_name] = self.groups.pop(old_name)
            
            # Update the list item
            item.setText(new_name)
            
            # Update active group if needed
            if self.active_group == old_name:
                self.active_group = new_name
                self.group_status.setText(f"Active: {new_name}")
            
            # Update plot (legend will show new name)
            self.update_plot()
            
            print(f"OK Renamed '{old_name}' to '{new_name}'")

    def on_group_selected(self, current, previous):
        """Handle group selection change"""
        if current:
            self.active_group = current.text()
            self.group_status.setText(f"Active: {self.active_group}")

    def on_group_checkbox_changed(self, item):
        """Handle group visibility checkbox change"""
        self.update_plot()

    # ===================================================================
    # DATA LOADING
    # ===================================================================

    def load_folder(self):
        """Load all files from a folder into the active group"""
        if not self.active_group:
            QMessageBox.warning(
                self, 
                "No Group Selected",
                "Please create and select a group first"
            )
            return
        
        # Get selected instrument type
        instrument = self.instrument_combo.currentText()
        
        # Set appropriate file extension filter
        if "Gamry" in instrument:
            file_pattern = "*.DTA"
            dialog_title = "Select Folder with .DTA Files"
        elif "ASCII" in instrument:
            file_pattern = "*.txt"
            dialog_title = "Select Folder with .txt Files"
        elif "Autolab" in instrument:
            file_pattern = "*.xlsx"
            dialog_title = "Select Folder with .xlsx Files"
        elif "Riden" in instrument:
            file_pattern = "*.xlsx"
            dialog_title = "Select Folder with .xlsx Files"
        elif "Custom CSV" in instrument:
            file_pattern = "*.csv"
            dialog_title = "Select Folder with .csv Files"
        else:
            file_pattern = "*.xlsx"
            dialog_title = "Select Folder with .xlsx Files"

        folder = QFileDialog.getExistingDirectory(self, dialog_title)
        if not folder:
            return
        
        folder_path = Path(folder)
        
        # Find files matching the pattern
        if "Gamry" in instrument:
            data_files = list(folder_path.glob("*.DTA"))
        elif "ASCII" in instrument:
            data_files = list(folder_path.glob("*.txt"))
        elif "Custom CSV" in instrument:
            data_files = list(folder_path.glob("*.csv"))
        else:  # Excel (Autolab & Riden)
            data_files = list(folder_path.glob("*.xlsx"))
        
        # Check if files were found
        if not data_files:
            file_ext = file_pattern.replace("*", "")
            QMessageBox.warning(
                self,
                "No Files Found",
                f"No {file_ext} files found in the selected folder"
            )
            return
        
        print(f"\nLOAD Loading files from: {folder}")
        
        # Load all files
        loaded_files = {}
        for file_path in sorted(data_files):
            try:
                # Load based on instrument type
                if "Gamry" in instrument:
                    data = load_gamry_file(file_path)
                elif "ASCII" in instrument:
                    data = load_autolab_chronopotentiometry_ascii(file_path)
                elif "Custom CSV" in instrument:
                    data = load_custom_csv(file_path)
                elif "Riden" in instrument:
                    data = load_riden_file(file_path)
                else:  # Excel (Autolab)
                    data = load_autolab_chronopotentiometry_excel(file_path)
                
                loaded_files[file_path.name] = data
                print(f"  OK {file_path.name}")
            except Exception as e:
                print(f"  ERROR {file_path.name}: {e}")
        
        if not loaded_files:
            QMessageBox.warning(
                self,
                "Loading Failed",
                "Failed to load any files from the folder"
            )
            return
        
        # Store files in active group
        self.groups[self.active_group]['files'] = loaded_files
        
        # Process data
        self.process_group(self.active_group)
        
        # Update UI
        num_files = len(loaded_files)
        self.load_status.setText(f"Loaded {num_files} files into {self.active_group}")
        self.load_status.setStyleSheet("color: green;")
        
        # Enable export buttons
        self.update_export_buttons()
        
        print(f"OK Loaded {num_files} files into {self.active_group}")
        
        # Auto-plot
        self.update_plot()

    def update_export_buttons(self):
        """Update export button states based on available data"""
        has_data = any(group['data'] is not None for group in self.groups.values())
        self.export_csv_btn.setEnabled(has_data)
        self.export_plot_btn.setEnabled(has_data)

    # ===================================================================
    # DATA PROCESSING
    # ===================================================================

    def load_single_file(self):
        """Load a single file into the active group (useful for Riden)"""
        if not self.active_group:
            QMessageBox.warning(
                self, 
                "No Group Selected",
                "Please create and select a group first"
            )
            return
        
        # Get selected instrument type
        instrument = self.instrument_combo.currentText()
        
        # Set appropriate file extension filter
        if "Gamry" in instrument:
            file_filter = "DTA Files (*.DTA);;All Files (*)"
            dialog_title = "Select .DTA File"
        elif "ASCII" in instrument:
            file_filter = "Text Files (*.txt);;All Files (*)"
            dialog_title = "Select .txt File"
        elif "Custom CSV" in instrument:
            file_filter = "CSV Files (*.csv);;All Files (*)"
            dialog_title = "Select .csv File"
        elif "Autolab" in instrument or "Riden" in instrument:
            file_filter = "Excel Files (*.xlsx);;All Files (*)"
            dialog_title = "Select .xlsx File"
        else:
            file_filter = "All Files (*)"
            dialog_title = "Select File"
        
        # Open file dialog
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            dialog_title,
            "",
            file_filter
        )
        
        if not file_path:
            return
        
        file_path = Path(file_path)
        
        print(f"\nLOAD Loading single file: {file_path}")
        
        # Load the file
        try:
            # Load based on instrument type
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
                # Store in active group with just this one file
                loaded_files = {file_path.name: data}
                self.groups[self.active_group]['files'] = loaded_files
                
                # Process data
                self.process_group(self.active_group)
                
                # Update UI
                self.load_status.setText(f"Loaded {file_path.name} into {self.active_group}")
                self.load_status.setStyleSheet("color: green;")
                
                # Enable export buttons
                self.update_export_buttons()
                
                print(f"  OK {file_path.name}")
                print(f"OK Loaded 1 file into {self.active_group}")
                
                # Auto-plot
                self.update_plot()
            else:
                QMessageBox.warning(
                    self,
                    "Loading Failed",
                    f"Failed to load {file_path.name}"
                )
                print(f"  ERROR {file_path.name}: Parser returned None")
        
        except Exception as e:
            QMessageBox.critical(
                self,
                "Loading Error",
                f"Error loading {file_path.name}:\n{str(e)}"
            )
            print(f"  ERROR {file_path.name}: {e}")
            import traceback
            traceback.print_exc()

    def process_group(self, group_name):
        """Process chronopotentiometry files to extract polarization curve"""
        group = self.groups[group_name]
        files = group['files']
        
        if not files:
            return
        
        print(f"\n⚙️ Processing {group_name}...")
        
        # Get parameters
        try:
            avg_time = float(self.avg_time_input.text())
            electrode_area = float(self.area_input.text())
        except ValueError:
            print("  ERROR Invalid parameters")
            return
        
        # Extract polarization data
        polarization_data = []
        step_data = {}
        
        for filename, data_obj in files.items():
            # Extract data from ElectrolyzerData object
            # ElectrolyzerData has attributes: time, voltage, current (pandas Series)
            if not hasattr(data_obj, 'time') or not hasattr(data_obj, 'voltage') or not hasattr(data_obj, 'current'):
                print(f"  ERROR {filename}: Missing required attributes")
                continue
            
            # Convert to string, replace European commas with dots, then to numeric
            # This handles cases where the data still has string values with commas
            time = pd.to_numeric(
                data_obj.time.astype(str).str.replace(',', '.'), 
                errors='coerce'
            ).values
            voltage = pd.to_numeric(
                data_obj.voltage.astype(str).str.replace(',', '.'), 
                errors='coerce'
            ).values
            current = pd.to_numeric(
                data_obj.current.astype(str).str.replace(',', '.'), 
                errors='coerce'
            ).values
            
            # Remove NaN values
            valid_mask = ~(np.isnan(time) | np.isnan(voltage) | np.isnan(current))
            time = time[valid_mask]
            voltage = voltage[valid_mask]
            current = current[valid_mask]
            
            if len(time) < 5:
                print(f"  ERROR {filename}: Insufficient data points")
                continue
            
            print(f"  DATA {filename}: {len(time)} points")
            
            # Detect current steps
            steps = self.detect_current_steps(time, current, voltage)
            
            if not steps:
                print(f"     WARNING  No valid steps detected")
                continue
            
            print(f"     OK Detected {len(steps)} step(s)")
            step_data[filename] = steps
            
            # Extract polarization points from each step
            for step_num, step in enumerate(steps, 1):
                # Calculate averaging window - use the minimum of:
                # 1. User's requested averaging time
                # 2. The full step duration (no artificial cap)
                steady_time = min(avg_time, step['duration'])
                
                # Get steady-state region (last portion of step)
                time_threshold = step['time_rel'][-1] - steady_time
                steady_mask = step['time_rel'] >= time_threshold
                
                if steady_mask.sum() < 3:
                    print(f"     WARNING  Step {step_num}: Too few steady-state points")
                    continue
                
                # Calculate averages
                current_density = step['I_mean'] / electrode_area
                voltage_avg = np.mean(step['voltage'][steady_mask])
                voltage_std = np.std(step['voltage'][steady_mask])
                
                polarization_data.append({
                    'file': filename,
                    'step': step_num,
                    'j': current_density,
                    'I_mean': step['I_mean'],
                    'V': voltage_avg,
                    'V_std': voltage_std,
                    'steady_start': time_threshold,
                    'steady_duration': steady_time
                })
                
                print(f"     OK Step {step_num}: j={current_density:.4f} A/cm², V={voltage_avg:.3f} V")
        
        # Store results
        if polarization_data:
            df_polar = pd.DataFrame(polarization_data).sort_values('j')
            group['data'] = df_polar
            group['steps'] = step_data
            print(f"OK Extracted {len(df_polar)} polarization points")
        else:
            group['data'] = None
            group['steps'] = None
            print("ERROR No polarization data extracted")

    def detect_current_steps(self, time, current, voltage, 
                            min_duration=5, tolerance=0.05):
        """
        Detect individual current steps in chronopotentiometry data.
        NO SMOOTHING - works with raw data to detect sharp transitions.
        """
        if len(time) < 10:
            return []
        
        # NO SMOOTHING AT ALL - use raw current
        diff = np.abs(np.diff(current))
        
        # Simple threshold: 1.0 mA (0.001 A) - filters out small fluctuations
        threshold = 0.0008
        
        # Find where current changes
        change_indices = np.where(diff > threshold)[0]
        
        # Group nearby changes (within 10 samples) as one transition
        if len(change_indices) > 0:
            grouped = [change_indices[0]]
            for idx in change_indices[1:]:
                if idx - grouped[-1] > 10:
                    grouped.append(idx)
            change_indices = np.array(grouped)
        
        # Add boundaries
        change_indices = np.unique(np.concatenate([[0], change_indices + 1, [len(time) - 1]]))
        
        steps = []
        rejected_count = 0
        
        # Check each segment
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
            else:
                rejected_count += 1
        
        # Fallback
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
        """Handle changes to processing parameters"""
        # Reprocess all groups
        for group_name in self.groups.keys():
            if self.groups[group_name]['files']:
                self.process_group(group_name)
        
        self.update_plot()

    # ===================================================================
    # PLOT INTERACTION - ENHANCED
    # ===================================================================

    def on_plot_click(self, event):
        """Handle click events on polarization curves"""
        # Only respond if interaction is enabled and left click on axes
        if not self.interaction_enabled or event.button != 1 or event.inaxes is None:
            return
        
        # Check if clicking on a polarization curve axis
        ax = event.inaxes
        
        # Remove previous annotation if exists
        if self.selected_annotation is not None:
            try:
                self.selected_annotation.remove()
            except Exception:
                pass
            self.selected_annotation = None

        # Get all visible groups
        visible_groups = self.get_visible_groups()
        if not visible_groups:
            return
        
        # Find closest point on any polarization curve
        min_distance = float('inf')
        closest_point = None
        
        for name, group in visible_groups:
            data = group['data']
            if data is None or len(data) == 0:
                continue
            
            # Convert to mA/cm² for comparison
            j_ma = data['j'].values * 1000
            V = data['V'].values
            I_mean = data['I_mean'].values
            
            # Calculate distance to click point
            for i in range(len(j_ma)):
                # Distance in plot coordinates
                try:
                    dx = (j_ma[i] - event.xdata) / (ax.get_xlim()[1] - ax.get_xlim()[0])
                    dy = (V[i] - event.ydata) / (ax.get_ylim()[1] - ax.get_ylim()[0])
                    distance = (dx**2 + dy**2)**0.5
                    
                    if distance < min_distance and distance < 0.05:  # Within 5% of plot size
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
        
        # If found a close point, handle selection
        if closest_point:
            self.selected_point = closest_point
            self.show_point_info(closest_point)
            
            # Highlight corresponding current step in transient plot
            self.highlight_current_step_in_transient(closest_point)
            
            if self.edit_mode:
                # Start drag operation
                self.dragging = True
                self.drag_start_pos = (event.xdata, event.ydata)

    def on_plot_motion(self, event):
        """Handle mouse motion for dragging points"""
        if not self.interaction_enabled or not self.edit_mode or not self.dragging:
            return
        
        if self.selected_point is None or event.inaxes != self.selected_point['ax']:
            return
        
        # Update point position
        new_j_ma = event.xdata
        new_V = event.ydata
        
        if new_j_ma is not None and new_V is not None:
            # Update the visual representation
            self.update_dragged_point(new_j_ma, new_V)

    def on_plot_release(self, event):
        """Handle mouse release to finish dragging"""
        if not self.interaction_enabled or not self.edit_mode or not self.dragging:
            return
        
        self.dragging = False
        
        if self.selected_point is None:
            return
        
        # Validate the new position
        new_j_ma = event.xdata
        new_V = event.ydata
        
        if new_j_ma is not None and new_V is not None and new_j_ma > 0:
            # Save state for undo
            self.save_state()
            
            # Update the actual data
            group_name = self.selected_point['group']
            index = self.selected_point['index']
            
            # Convert back from mA/cm² to A/cm²
            new_j_A = new_j_ma / 1000
            
            # Update the data
            self.groups[group_name]['data'].loc[index, 'j'] = new_j_A
            self.groups[group_name]['data'].loc[index, 'V'] = new_V
            
            # Update status
            self.interaction_status.setText(f"Modified point: j={new_j_ma:.2f} mA/cm², V={new_V:.3f} V")
            self.load_status.setText("✓ Data modified - changes will be included in exports")
            
            # Update plot
            self.update_plot()
            
            print(f"EDIT Point modified: j={new_j_ma:.2f} mA/cm², V={new_V:.3f} V")

    def update_dragged_point(self, new_j_ma, new_V):
        """Update visual representation of dragged point"""
        # This is called during dragging to provide visual feedback
        # We'll update this when we refresh the plot
        pass

    def show_point_info(self, point_info):
        """Show information about the selected point"""
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
            arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0.3', 
                           color='black', lw=1.5),
            fontsize=9, fontweight='bold'
        )
        
        # Highlight the point
        highlight = point_info['ax'].plot(point_info['j_ma'], point_info['V'], 'ro', 
               markersize=10, markerfacecolor='none', markeredgewidth=2)[0]
        highlight._temp_highlight = True  # Mark for cleanup
        
        # Update status
        status_text = f"Selected: {point_info['name']} - j={point_info['j_ma']:.2f} mA/cm², V={point_info['V']:.3f} V"
        if self.edit_mode:
            status_text += " (Drag to edit)"
        self.interaction_status.setText(status_text)
        
        self.canvas.draw_idle()

    # ===================================================================
    # CSV EXPORT - NEW
    # ===================================================================

    def export_csv_data(self):
        """Export data to CSV with options"""
        # Check if there's data to export
        if not any(group['data'] is not None for group in self.groups.values()):
            QMessageBox.warning(
                self,
                "No Data",
                "Please load and analyze data before exporting"
            )
            return
        
        # Open export dialog
        dialog = CSVExportDialog(self, self.groups)
        if dialog.exec_() != QDialog.Accepted:
            return
        
        settings = dialog.get_export_settings()
        
        if not settings['groups']:
            QMessageBox.warning(
                self,
                "No Groups Selected",
                "Please select at least one group to export"
            )
            return
        
        # Determine export path
        if settings['separate_files']:
            folder = QFileDialog.getExistingDirectory(
                self,
                "Select Export Folder"
            )
            if not folder:
                return
            export_folder = Path(folder)
        else:
            if settings['data_type'] == 'polarization':
                default_name = "polarization_curves.csv"
            else:
                default_name = "transient_data.csv"
            
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save CSV File",
                default_name,
                "CSV Files (*.csv);;All Files (*)"
            )
            if not filepath:
                return
            export_folder = Path(filepath).parent
            single_filename = Path(filepath).name
        
        try:
            exported_files = []
            
            if settings['data_type'] == 'polarization':
                exported_files = self.export_polarization_csv(
                    settings, export_folder, 
                    single_filename if not settings['separate_files'] else None
                )
            else:
                exported_files = self.export_transient_csv(
                    settings, export_folder,
                    single_filename if not settings['separate_files'] else None
                )
            
            # Show success message
            if len(exported_files) == 1:
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Data exported to:\n{exported_files[0]}"
                )
            else:
                file_list = '\n'.join([f"• {f.name}" for f in exported_files])
                QMessageBox.information(
                    self,
                    "Export Successful",
                    f"Data exported to {len(exported_files)} files:\n\n{file_list}"
                )
            
            self.load_status.setText(f"✓ Data exported to {len(exported_files)} CSV file(s)")
            
        except Exception as e:
            QMessageBox.critical(
                self,
                "Export Failed",
                f"Error exporting data:\n{str(e)}"
            )

    def export_polarization_csv(self, settings, export_folder, single_filename=None):
        """Export polarization curve data to CSV"""
        exported_files = []
        
        if settings['separate_files']:
            # Export each group to separate file
            for group_name in settings['groups']:
                group = self.groups[group_name]
                data = group['data']
                
                if data is None:
                    continue
                
                # Create filename
                safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"polarization_{safe_name}.csv"
                filepath = export_folder / filename
                
                # Prepare data
                export_data = data.copy()
                export_data['Group'] = group_name
                
                # Convert current density to mA/cm²
                export_data['j_mA_cm2'] = export_data['j'] * 1000
                
                # Reorder columns
                columns = ['Group', 'file', 'step', 'j_mA_cm2', 'j', 'V', 'V_std', 'I_mean', 
                          'steady_start', 'steady_duration']
                export_data = export_data[columns]
                
                # Add metadata if requested
                if settings['include_metadata']:
                    metadata_lines = [
                        f"# Polarization Curve Data - Group: {group_name}",
                        f"# Exported from Electrolyzer Analyzer",
                        f"# Processing parameters:",
                        f"# - Averaging time: {self.avg_time_input.text()} s",
                        f"# - Electrode area: {self.area_input.text()} cm²",
                        f"# Columns:",
                        f"# - Group: Group name",
                        f"# - file: Source filename",
                        f"# - step: Step number in chronopotentiometry",
                        f"# - j_mA_cm2: Current density (mA/cm²)",
                        f"# - j: Current density (A/cm²)",
                        f"# - V: Voltage (V)",
                        f"# - V_std: Voltage standard deviation (V)",
                        f"# - I_mean: Mean current (A)",
                        f"# - steady_start: Start of steady-state region (s)",
                        f"# - steady_duration: Duration of averaging window (s)",
                        ""
                    ]
                    
                    # Write metadata and data
                    with open(filepath, 'w') as f:
                        f.write('\n'.join(metadata_lines))
                        export_data.to_csv(f, index=False)
                else:
                    export_data.to_csv(filepath, index=False)
                
                exported_files.append(filepath)
                
        else:
            # Export all groups to single file
            all_data = []
            
            for group_name in settings['groups']:
                group = self.groups[group_name]
                data = group['data']
                
                if data is None:
                    continue
                
                group_data = data.copy()
                group_data['Group'] = group_name
                all_data.append(group_data)
            
            if all_data:
                combined_data = pd.concat(all_data, ignore_index=True)
                
                # Convert current density to mA/cm²
                combined_data['j_mA_cm2'] = combined_data['j'] * 1000
                
                # Reorder columns
                columns = ['Group', 'file', 'step', 'j_mA_cm2', 'j', 'V', 'V_std', 'I_mean', 
                          'steady_start', 'steady_duration']
                combined_data = combined_data[columns]
                
                filepath = export_folder / single_filename
                
                if settings['include_metadata']:
                    metadata_lines = [
                        f"# Combined Polarization Curve Data",
                        f"# Exported from Electrolyzer Analyzer",
                        f"# Groups included: {', '.join(settings['groups'])}",
                        f"# Processing parameters:",
                        f"# - Averaging time: {self.avg_time_input.text()} s",
                        f"# - Electrode area: {self.area_input.text()} cm²",
                        f"# Columns:",
                        f"# - Group: Group name",
                        f"# - file: Source filename",
                        f"# - step: Step number in chronopotentiometry",
                        f"# - j_mA_cm2: Current density (mA/cm²)",
                        f"# - j: Current density (A/cm²)",
                        f"# - V: Voltage (V)",
                        f"# - V_std: Voltage standard deviation (V)",
                        f"# - I_mean: Mean current (A)",
                        f"# - steady_start: Start of steady-state region (s)",
                        f"# - steady_duration: Duration of averaging window (s)",
                        ""
                    ]
                    
                    with open(filepath, 'w') as f:
                        f.write('\n'.join(metadata_lines))
                        combined_data.to_csv(f, index=False)
                else:
                    combined_data.to_csv(filepath, index=False)
                
                exported_files.append(filepath)
        
        return exported_files

    def export_transient_csv(self, settings, export_folder, single_filename=None):
        """Export transient (chronopotentiometry) data to CSV"""
        exported_files = []
        
        if settings['separate_files']:
            # Export each group to separate file
            for group_name in settings['groups']:
                group = self.groups[group_name]
                steps = group['steps']
                
                if not steps:
                    continue
                
                # Create filename
                safe_name = "".join(c for c in group_name if c.isalnum() or c in (' ', '-', '_')).strip()
                filename = f"transient_{safe_name}.csv"
                filepath = export_folder / filename
                
                # Combine all transient data for this group
                all_transient_data = []
                
                for filename_key, file_steps in steps.items():
                    for step_idx, step in enumerate(file_steps, 1):
                        step_data = pd.DataFrame({
                            'time': step['time'],
                            'time_rel': step['time_rel'],
                            'voltage': step['voltage'],
                            'current': step['current'],
                            'current_mA': step['current'] * 1000,
                            'file': filename_key,
                            'step': step_idx,
                            'group': group_name
                        })
                        all_transient_data.append(step_data)
                
                if all_transient_data:
                    combined_data = pd.concat(all_transient_data, ignore_index=True)
                    
                    # Add metadata if requested
                    if settings['include_metadata']:
                        metadata_lines = [
                            f"# Transient (Chronopotentiometry) Data - Group: {group_name}",
                            f"# Exported from Electrolyzer Analyzer",
                            f"# Columns:",
                            f"# - time: Absolute time (s)",
                            f"# - time_rel: Relative time within step (s)",
                            f"# - voltage: Voltage (V)",
                            f"# - current: Current (A)",
                            f"# - current_mA: Current (mA)",
                            f"# - file: Source filename",
                            f"# - step: Step number",
                            f"# - group: Group name",
                            ""
                        ]
                        
                        with open(filepath, 'w') as f:
                            f.write('\n'.join(metadata_lines))
                            combined_data.to_csv(f, index=False)
                    else:
                        combined_data.to_csv(filepath, index=False)
                    
                    exported_files.append(filepath)
        
        else:
            # Export all groups to single file
            all_transient_data = []
            
            for group_name in settings['groups']:
                group = self.groups[group_name]
                steps = group['steps']
                
                if not steps:
                    continue
                
                for filename_key, file_steps in steps.items():
                    for step_idx, step in enumerate(file_steps, 1):
                        step_data = pd.DataFrame({
                            'time': step['time'],
                            'time_rel': step['time_rel'],
                            'voltage': step['voltage'],
                            'current': step['current'],
                            'current_mA': step['current'] * 1000,
                            'file': filename_key,
                            'step': step_idx,
                            'group': group_name
                        })
                        all_transient_data.append(step_data)
            
            if all_transient_data:
                combined_data = pd.concat(all_transient_data, ignore_index=True)
                filepath = export_folder / single_filename
                
                if settings['include_metadata']:
                    metadata_lines = [
                        f"# Combined Transient (Chronopotentiometry) Data",
                        f"# Exported from Electrolyzer Analyzer",
                        f"# Groups included: {', '.join(settings['groups'])}",
                        f"# Columns:",
                        f"# - time: Absolute time (s)",
                        f"# - time_rel: Relative time within step (s)",
                        f"# - voltage: Voltage (V)",
                        f"# - current: Current (A)",
                        f"# - current_mA: Current (mA)",
                        f"# - file: Source filename",
                        f"# - step: Step number",
                        f"# - group: Group name",
                        ""
                    ]
                    
                    with open(filepath, 'w') as f:
                        f.write('\n'.join(metadata_lines))
                        combined_data.to_csv(f, index=False)
                else:
                    combined_data.to_csv(filepath, index=False)
                
                exported_files.append(filepath)
        
        return exported_files

    # ===================================================================
    # EXPORT FUNCTIONALITY (PLOT)
    # ===================================================================

    def export_plot(self):
        """Export current plot with custom settings"""
        # Check if there's something to export
        visible_groups = self.get_visible_groups()
        if not visible_groups:
            QMessageBox.warning(
                self,
                "No Data",
                "Please load and display data before exporting"
            )
            return
        
        # Open export dialog
        dialog = ExportDialog(self)
        if dialog.exec_() == QDialog.Accepted:
            settings = dialog.get_settings()
            
            # Ask for save location
            file_filter = f"{settings['format'].upper()} Files (*.{settings['format']})"
            filepath, _ = QFileDialog.getSaveFileName(
                self,
                "Save Plot",
                f"polarization_curve.{settings['format']}",
                file_filter
            )
            
            if filepath:
                try:
                    # Save current figure size
                    original_size = self.fig.get_size_inches()
                    
                    # Set new size
                    self.fig.set_size_inches(settings['width'], settings['height'])
                    
                    # Save with specified DPI
                    self.fig.savefig(
                        filepath,
                        dpi=settings['dpi'],
                        format=settings['format'],
                        bbox_inches='tight',
                        facecolor='white'
                    )
                    
                    # Restore original size
                    self.fig.set_size_inches(original_size)
                    self.canvas.draw()
                    
                    QMessageBox.information(
                        self,
                        "Export Successful",
                        f"Plot saved to:\n{filepath}"
                    )
                    
                except Exception as e:
                    QMessageBox.critical(
                        self,
                        "Export Failed",
                        f"Error saving plot:\n{str(e)}"
                    )

    # ===================================================================
    # PLOTTING
    # ===================================================================

    def update_plot(self):
        """Main plotting dispatcher"""
        self.fig.clear()
        
        # Clear point tracking
        # Clear highlights when replotting
        self.transient_highlights.clear()

        self.point_artists.clear()
        self.selected_annotation = None
        
        # Get visible groups
        visible_groups = self.get_visible_groups()
        
        if not visible_groups:
            self.empty_plot()
            return
        
        # Choose plot type
        if self.radio_with_transient.isChecked():
            if len(visible_groups) == 1:
                self.plot_single_with_transient(visible_groups[0])
            else:
                self.plot_multi_with_transient(visible_groups)
        else:
            if self.radio_grid.isChecked() and len(visible_groups) > 1:
                self.plot_polarization_grid(visible_groups)
            else:
                self.plot_polarization_overlay(visible_groups)
        
        # Use try-except to handle tight_layout issues with twin axes
        try:
            # Use subplots_adjust instead of tight_layout for better control
            # This adds extra space on the right for the secondary y-axis
            self.fig.subplots_adjust(left=0.1, right=0.88, top=0.95, bottom=0.08)
        except Exception:
            pass  # Skip if adjustment fails
        
        self.canvas.draw()

    def get_visible_groups(self):
        """Get list of visible groups with valid data"""
        visible = []
        
        for i in range(self.group_list.count()):
            item = self.group_list.item(i)
            if item and item.checkState() == Qt.Checked:
                group_name = item.text()
                if group_name in self.groups and self.groups[group_name]['data'] is not None:
                    visible.append((group_name, self.groups[group_name]))
        
        return visible

    def plot_polarization_overlay(self, groups):
        """Plot polarization curves overlaid on single axis"""
        ax = self.fig.add_subplot(111)
        
        for i, (name, group) in enumerate(groups):
            data = group['data']
            color = self.colors[i % len(self.colors)]
            
            # Convert j from A/cm² to mA/cm²
            j_ma = data['j'] * 1000
            
            line, = ax.plot(
                j_ma, data['V'],
                marker='o', linestyle='-',
                color=color, label=name,
                markersize=6, linewidth=2
            )
            
            # Store artist references for interaction
            if self.interaction_enabled:
                self.point_artists[name] = line
        
        ax.set_xlabel('Current Density [mA/cm²]', fontsize=16, fontweight='bold')
        ax.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
        ax.tick_params(axis='both', labelsize=14)
        ax.set_title('Polarization Curves', fontsize=14, fontweight='bold')
        ax.grid(True, alpha=0.3, linestyle='--')
        ax.legend(fontsize=14, loc='best', framealpha=0.9)

    def plot_polarization_grid(self, groups):
        """Plot polarization curves in grid layout"""
        n = len(groups)
        cols = min(2, n)
        rows = (n + cols - 1) // cols
        
        for i, (name, group) in enumerate(groups):
            ax = self.fig.add_subplot(rows, cols, i + 1)
            data = group['data']
            color = self.colors[i % len(self.colors)]
            
            # Convert j from A/cm² to mA/cm²
            j_ma = data['j'] * 1000
            
            line, = ax.plot(
                j_ma, data['V'],
                marker='o', linestyle='-',
                color=color,
                markersize=5, linewidth=1.5
            )
            
            # Store artist references for interaction
            if self.interaction_enabled:
                self.point_artists[f"{name}_{i}"] = line
            
            ax.set_title(name, fontsize=14, fontweight='bold')
            ax.set_xlabel('j [mA/cm²]', fontsize=16)
            ax.set_ylabel('V [V]', fontsize=16)
            ax.tick_params(axis='both', labelsize=14)
            ax.grid(True, alpha=0.3, linestyle='--')

    def plot_single_with_transient(self, group_tuple):
        """Plot polarization curve with voltage transients for single group"""
        name, group = group_tuple
        data = group['data']
        steps = group['steps']
        
        # Create two subplots
        gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1.5], hspace=0.3)
        ax1 = self.fig.add_subplot(gs[0])  # Polarization (top)
        ax2 = self.fig.add_subplot(gs[1])  # Transients (bottom)
                
        color = self.colors[0]
        
        # Top: Polarization curve
        j_ma = data['j'] * 1000  # Convert to mA/cm²
        line, = ax1.plot(
            j_ma, data['V'],
            marker='o', linestyle='-',
            color=color,
            markersize=7, linewidth=2
        )
        
        # Store artist reference for interaction
        if self.interaction_enabled:
            self.point_artists[name] = line
        
        ax1.set_xlabel('Current Density [mA/cm²]', fontsize=16, fontweight='bold')
        ax1.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
        ax1.tick_params(axis='both', labelsize=14)
        ax1.set_title(f'Polarization Curve - {name}', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3, linestyle='--')
        
        # Bottom: Voltage transients with highlighted steady-state regions
        ax2_voltage = ax2
        ax2_current = ax2.twinx()  # Secondary y-axis for current
        
        time_offset = 0
        previous_current = None
        
        for filename in sorted(steps.keys()):
            file_steps = steps[filename]
            
            for step_idx, step in enumerate(file_steps):
                # Use relative time (starting at 0 for each step) + offset
                t = step['time_rel'] + time_offset
                V = step['voltage']
                I = step['current']
                current_mean = step['I_mean']
                
                # Plot voltage (primary axis)
                ax2_voltage.plot(t, V, 'o', markersize=4, alpha=0.8, color=color, label='Voltage' if time_offset == 0 else "")
                
                # Plot current as STEP FUNCTION (horizontal lines) - in milliamps
                ax2_current.hlines(current_mean * 1000, t[0], t[-1], colors='gray', linestyles='--', 
                                  linewidth=2, alpha=0.7, label='Current' if time_offset == 0 else "")
                
                # Draw vertical line at current transitions (between steps)
                if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                    ax2_voltage.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                
                previous_current = current_mean
                
                # Find matching polarization data point
                matching = data[
                    (data['file'] == filename) &
                    (np.isclose(data['I_mean'], step['I_mean'], rtol=0.01))
                ]
                
                if len(matching) > 0:
                    row = matching.iloc[0]
                    ss_start = row['steady_start']
                    
                    # Highlight steady-state region
                    ss_mask = step['time_rel'] >= ss_start
                    t_ss = step['time_rel'][ss_mask] + time_offset
                    V_ss = step['voltage'][ss_mask]
                    
                    if len(V_ss) > 0:
                        ax2_voltage.fill_between(
                            t_ss, 
                            V_ss.min() - 0.01, 
                            V_ss.max() + 0.01,
                            alpha=0.3, 
                            color='yellow',
                            label='Steady-state region' if time_offset == 0 else ""
                        )
                        
                        # Mark average voltage
                        ax2_voltage.plot(
                            [t_ss[0], t_ss[-1]], 
                            [row['V'], row['V']],
                            'r--', linewidth=2, alpha=0.7,
                            label='Average voltage' if time_offset == 0 else ""
                        )
                
                # Update offset - NO GAP, continuous time
                time_offset = t[-1]
        
        ax2_voltage.set_xlabel('Time [s]', fontsize=16, fontweight='bold')
        ax2_voltage.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold', color='black')
        ax2_voltage.tick_params(axis='y', labelcolor='black')
        ax2_current.set_ylabel('Current [mA]', fontsize=16, fontweight='bold', color='gray')
        ax2_current.tick_params(axis='y', labelcolor='gray')
        ax2_voltage.set_title('Voltage Transients', fontsize=16, fontweight='bold')
        ax2_voltage.grid(True, alpha=0.3, linestyle='--')
        
        # Combine legends
        lines1, labels1 = ax2_voltage.get_legend_handles_labels()
        lines2, labels2 = ax2_current.get_legend_handles_labels()
        by_label = dict(zip(labels1 + labels2, lines1 + lines2))
        ax2_voltage.legend(by_label.values(), by_label.keys(), fontsize=14, loc='best', framealpha=0.9)

    def plot_multi_with_transient(self, groups):
        """Plot multiple groups with transients - grid or overlay mode"""
        n = len(groups)
        
        # Check if overlay mode for transients
        overlay_mode = self.radio_overlay.isChecked()
        
        if overlay_mode:
            # OVERLAY MODE: Vertical layout like single group
            # Top: All polarization curves together
            # Bottom: All transients together
            gs = GridSpec(2, 1, figure=self.fig, height_ratios=[1, 1.5], hspace=0.3)
            ax1 = self.fig.add_subplot(gs[0])  # Polarization on top
            ax2 = self.fig.add_subplot(gs[1])  # Transients on bottom
            ax2_current = ax2.twinx()
            
            # Plot all polarization curves
            for i, (name, group) in enumerate(groups):
                data = group['data']
                color = self.colors[i % len(self.colors)]
                j_ma = data['j'] * 1000
                line, = ax1.plot(j_ma, data['V'], 'o-', color=color, label=name, 
                        markersize=6, linewidth=2)
                
                # Store artist reference for interaction
                if self.interaction_enabled:
                    self.point_artists[name] = line
            
            ax1.set_xlabel('Current Density [mA/cm²]', fontsize=16, fontweight='bold')
            ax1.set_ylabel('Voltage [V]', fontsize=16, fontweight='bold')
            ax1.tick_params(axis='both', labelsize=14)
            ax1.set_title('Polarization Curves', fontsize=14, fontweight='bold')
            ax1.legend(fontsize=14, loc='best', framealpha=0.9)
            ax1.grid(True, alpha=0.3, linestyle='--')
            
            # Plot all transients
            for i, (name, group) in enumerate(groups):
                data = group['data']
                steps = group['steps']
                color = self.colors[i % len(self.colors)]
                
                time_offset = 0
                previous_current = None
                
                for filename in sorted(steps.keys()):
                    for step in steps[filename]:
                        t = step['time_rel'] + time_offset
                        current_mean = step['I_mean']
                        
                        # Plot voltage
                        ax2.plot(t, step['voltage'], 'o', color=color, markersize=4, alpha=0.8,
                                label=name if time_offset == 0 else "")
                        
                        # Plot current as step function (mA) - only once for all groups
                        if i == 0:  # Only plot current once (shared across all groups)
                            ax2_current.hlines(current_mean * 1000, t[0], t[-1], 
                                              colors='gray', linestyles='--', linewidth=2, alpha=0.7,
                                              label='Current' if time_offset == 0 and i == 0 else "")
                        
                        # Vertical lines at transitions
                        if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                            ax2.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                        
                        previous_current = current_mean
                        
                        # Highlight steady-state
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
                                ax2.fill_between(t_ss, V_ss.min() - 0.01, V_ss.max() + 0.01,
                                               alpha=0.3, color='yellow',
                                               label='Steady-state region' if time_offset == 0 and i == 0 else "")
                                ax2.plot([t_ss[0], t_ss[-1]], [row['V'], row['V']],
                                       'r--', linewidth=2, alpha=0.7,
                                       label='Average voltage' if time_offset == 0 and i == 0 else "")
                        
                        time_offset = t[-1]
            
            ax2.set_xlabel('Time [s]', fontsize=11, fontweight='bold')
            ax2.set_ylabel('Voltage [V]', fontsize=11, fontweight='bold', color='black')
            ax2.tick_params(axis='y', labelcolor='black')
            ax2_current.set_ylabel('Current [mA]', fontsize=11, fontweight='bold', color='gray')
            ax2_current.tick_params(axis='y', labelcolor='gray')
            ax2.set_title('Voltage Transients', fontsize=13, fontweight='bold')
            ax2.grid(True, alpha=0.3, linestyle='--')
            
            # Combine legends
            lines1, labels1 = ax2.get_legend_handles_labels()
            lines2, labels2 = ax2_current.get_legend_handles_labels()
            by_label = dict(zip(labels1 + labels2, lines1 + lines2))
            ax2.legend(by_label.values(), by_label.keys(), fontsize=14, loc='best', framealpha=0.9)
            
        else:
            # GRID MODE: Separate row for each group
            for i, (name, group) in enumerate(groups):
                data = group['data']
                steps = group['steps']
                color = self.colors[i % len(self.colors)]
                
                # Polarization (left)
                ax1 = self.fig.add_subplot(n, 2, 2*i + 1)
                j_ma = data['j'] * 1000
                line, = ax1.plot(j_ma, data['V'], 'o', color=color)
                
                # Store artist reference for interaction
                if self.interaction_enabled:
                    self.point_artists[f"{name}_polar"] = line
                
                ax1.set_title(f'{name} - Polarization', fontsize=10, fontweight='bold')
                ax1.set_xlabel('j [mA/cm²]', fontsize=9)
                ax1.set_ylabel('V [V]', fontsize=9)
                ax1.grid(True, alpha=0.3)
                
                # Transients (right)
                ax2 = self.fig.add_subplot(n, 2, 2*i + 2)
                ax2_current = ax2.twinx()
                
                time_offset = 0
                previous_current = None
                
                for filename in sorted(steps.keys()):
                    for step in steps[filename]:
                        t = step['time_rel'] + time_offset
                        current_mean = step['I_mean']
                        
                        # Plot voltage
                        ax2.plot(t, step['voltage'], 'o', color=color, markersize=3, alpha=0.7)
                        
                        # Plot current as step function (mA)
                        ax2_current.hlines(current_mean * 1000, t[0], t[-1],
                                          colors='gray', linestyles='--', linewidth=1.5, alpha=0.7)
                        
                        # Vertical lines at transitions
                        if previous_current is not None and abs(current_mean - previous_current) > 0.0001:
                            ax2.axvline(t[0], color='red', linestyle=':', linewidth=1, alpha=0.5)
                        
                        previous_current = current_mean
                        
                        # Highlight steady-state
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
        """Show empty plot with instructions"""
        self.fig.clear()
        ax = self.fig.add_subplot(111)
        
        instructions = (
            "Polarization Curve Analysis\n\n"
            "Getting Started:\n"
            "1. Click '+ New' to create a group\n"
            "2. Click 'Load Folder into Group'\n"
            "3. Select folder containing .DTA files\n\n"
            "The app will automatically:\n"
            "- Detect current steps\n"
            "- Extract steady-state voltages\n"
            "- Build polarization curve\n\n"
            "New Features:\n"
            "- Enable data interaction to click/edit points\n"
            "- Export CSV data (polarization/transient)\n"
            "- Modified data included in exports"
        )
        
        ax.text(
            0.5, 0.5, instructions,
            ha='center', va='center',
            fontsize=11, color='gray',
            transform=ax.transAxes
        )
        ax.axis('off')
        self.canvas.draw()


class ExportDialog(QDialog):
    """Dialog for customizing plot export settings"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Export Plot Settings")
        self.setModal(True)
        
        layout = QVBoxLayout(self)
        
        # Size settings
        size_group = QGroupBox("Plot Size (inches)")
        size_layout = QVBoxLayout()
        
        # Width
        width_layout = QHBoxLayout()
        width_layout.addWidget(QLabel("Width:"))
        self.width_spin = QSpinBox()
        self.width_spin.setRange(4, 24)
        self.width_spin.setValue(10)
        self.width_spin.setSuffix(" in")
        width_layout.addWidget(self.width_spin)
        size_layout.addLayout(width_layout)
        
        # Height
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
        
        # DPI settings
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
        
        # Format settings
        format_group = QGroupBox("File Format")
        format_layout = QHBoxLayout()
        format_layout.addWidget(QLabel("Format:"))
        self.format_combo = QComboBox()
        self.format_combo.addItems(['png', 'pdf', 'svg', 'jpg', 'tiff'])
        self.format_combo.setCurrentText('png')
        format_layout.addWidget(self.format_combo)
        format_group.setLayout(format_layout)
        layout.addWidget(format_group)
        
        # Preset buttons
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
        
        # Dialog buttons
        button_layout = QHBoxLayout()
        ok_btn = QPushButton("Export")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(ok_btn)
        button_layout.addWidget(cancel_btn)
        layout.addLayout(button_layout)
    
    def apply_preset(self, width, height):
        """Apply preset size"""
        self.width_spin.setValue(width)
        self.height_spin.setValue(height)
    
    def get_settings(self):
        """Get export settings from dialog"""
        return {
            'width': self.width_spin.value(),
            'height': self.height_spin.value(),
            'dpi': int(self.dpi_combo.currentText()),
            'format': self.format_combo.currentText()
        }