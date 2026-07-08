"""
Main GUI window with 3 tabs: EIS, Polarization, Chronopotentiometry
"""

import sys
from PyQt5.QtWidgets import QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout
from PyQt5.QtCore import Qt

from gui.widgets.eis_tab import EISTab
from gui.widgets.polarization_tab import PolarizationTab
from gui.widgets.chronopotentiometry_tab import ChronopotentiometryTab


class ElectrolyzerAnalyzer(QMainWindow):
    """Main application window with tabbed interface"""
    
    def __init__(self):
        super().__init__()
        self.init_ui()
    
    def init_ui(self):
        """Initialize the user interface"""
        
        self.setWindowTitle("pyEAT: Electrolysis Analysis Tool")
        self.setGeometry(100, 100, 1400, 900)
        
        # Create central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main layout
        layout = QVBoxLayout(central_widget)
        
        # Create tab widget
        self.tabs = QTabWidget()
        
        # Create the three tabs
        self.eis_tab = EISTab()
        self.polarization_tab = PolarizationTab()
        self.chronopotentiometry_tab = ChronopotentiometryTab()
        
        # Add tabs
        self.tabs.addTab(self.eis_tab, "EIS")
        self.tabs.addTab(self.polarization_tab, "Polarization Curves")
        self.tabs.addTab(self.chronopotentiometry_tab, "Chronopotentiometry")
        
        layout.addWidget(self.tabs)
        
        # Create menu bar
        self.create_menu_bar()
        
        # Status bar
        self.statusBar().showMessage("Ready - Select a tab and load data")
    
    def create_menu_bar(self):
        """Create application menu bar"""
        
        menubar = self.menuBar()
        
        # File menu
        file_menu = menubar.addMenu('File')
        
        exit_action = file_menu.addAction('Exit')
        exit_action.triggered.connect(self.close)
        
        # Help menu
        help_menu = menubar.addMenu('Help')
        
        about_action = help_menu.addAction('About')
        about_action.triggered.connect(self.show_about)
    
    def show_about(self):
        """Show about dialog"""
        from PyQt5.QtWidgets import QMessageBox
        
        QMessageBox.about(
            self,
            "About pyEAT",
            "pyEAT: a Python Electrolysis Analysis Tool"
        )


def main():
    """Main entry point"""
    app = QApplication(sys.argv)
    window = ElectrolyzerAnalyzer()
    window.showMaximized()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()