"""
Autolab file parser - PANDAS 3.0 COMPATIBLE
Supports both ASCII (.txt) and Excel (.xlsx) formats
Handles EIS and Chronopotentiometry data
"""

import pandas as pd
import numpy as np
from pathlib import Path
import sys

# Add parent directory to path to import core modules
sys.path.append(str(Path(__file__).parent.parent))
from core.data_model import ElectrolyzerData


def load_autolab_ascii(file_path):
    """
    Load Autolab ASCII EIS file (.txt)
    
    Args:
        file_path: Path to .txt file
        
    Returns:
        ElectrolyzerData object or None if parsing fails
    """
    try:
        file_path = Path(file_path)
        
        # Read data using pandas with proper settings for Autolab format
        # Autolab uses semicolon separator and comma as decimal
        df = pd.read_csv(
            file_path,
            sep=';',           # Semicolon-separated
            decimal=',',       # Comma as decimal separator
            encoding='utf-8'
        )
        
        # Clean column names (remove whitespace, make lowercase)
        df.columns = df.columns.str.strip().str.lower()
        
        print(f"Available columns: {list(df.columns)}")
        
        # Try to identify columns
        # Autolab format: frequency (hz), z' (ω), -z'' (ω)
        
        freq_col = None
        zreal_col = None
        zimag_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            
            # Frequency
            if 'frequency' in col_lower:
                freq_col = col
            
            # Z' is real impedance (look for z' but NOT -z'')
            elif "z'" in col_lower and "-z''" not in col_lower:
                zreal_col = col
            
            # -Z'' is negative imaginary (look for -z'')
            elif "-z''" in col_lower:
                zimag_col = col
        
        if not all([freq_col, zreal_col, zimag_col]):
            print(f"Could not identify required columns in {file_path}")
            print(f"Found - Freq: {freq_col}, Zreal: {zreal_col}, Zimag: {zimag_col}")
            return None
        
        print(f"Matched columns - Freq: {freq_col}, Zreal: {zreal_col}, Zimag: {zimag_col}")
        
        # PANDAS 3.0 COMPATIBILITY: Ensure all data is properly numeric
        # The decimal=',' parameter should have handled this, but we double-check
        freq_data = pd.to_numeric(df[freq_col], errors='coerce')
        zreal_data = pd.to_numeric(df[zreal_col], errors='coerce')
        zimag_data = pd.to_numeric(df[zimag_col], errors='coerce')
        
        # Remove any NaN values
        valid_mask = ~(freq_data.isna() | zreal_data.isna() | zimag_data.isna())
        
        freq_data = freq_data[valid_mask].reset_index(drop=True)
        zreal_data = zreal_data[valid_mask].reset_index(drop=True)
        zimag_data = zimag_data[valid_mask].reset_index(drop=True)
        
        # Autolab exports -Z'', but we store positive imaginary
        # So negate the column to get positive imaginary
        zimag_data = -zimag_data
        
        # Create time series (just an index, like Gamry does for EIS)
        time_series = pd.Series(range(len(freq_data)), name='index')
        
        # Create ElectrolyzerData object (matching Gamry's EIS pattern)
        data = ElectrolyzerData(
            technique='eis',
            instrument='autolab',
            time=time_series,
            voltage=pd.Series([0] * len(freq_data)),  # EIS doesn't have voltage series
            current=pd.Series([0] * len(freq_data)),  # EIS doesn't have current series
            frequency=freq_data,
            z_real=zreal_data,
            z_imag=zimag_data,
            source_file=file_path
        )
        
        print(f"✓ Loaded Autolab ASCII: {file_path.name}")
        print(f"  Shape: {len(data.frequency)} points")
        print(f"  Frequency range: {data.frequency.min():.3f} - {data.frequency.max():.3f} Hz")
        print(f"  Z_real range: {data.z_real.min():.3f} - {data.z_real.max():.3f} Ω")
        print(f"  Z_imag range: {data.z_imag.min():.3f} - {data.z_imag.max():.3f} Ω")
        
        return data
        
    except Exception as e:
        print(f"Error loading Autolab ASCII file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_autolab_excel(file_path):
    """
    Load Autolab Excel EIS file (.xlsx)
    
    Args:
        file_path: Path to .xlsx file
        
    Returns:
        ElectrolyzerData object or None if parsing fails
    """
    try:
        file_path = Path(file_path)
        
        # Try to read the Excel file
        # Autolab often puts data in the first sheet
        df = pd.read_excel(file_path, sheet_name=0)
        
        # Clean column names (remove whitespace, make lowercase)
        df.columns = df.columns.str.strip().str.lower()
        
        print(f"Available columns: {list(df.columns)}")
        
        # Try to identify columns
        freq_col = None
        zreal_col = None
        zimag_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            
            # Frequency
            if 'frequency' in col_lower:
                freq_col = col
            
            # Z' is real impedance (look for z' but NOT -z'')
            elif "z'" in col_lower and "-z''" not in col_lower:
                zreal_col = col
            
            # -Z'' is negative imaginary (look for -z'')
            elif "-z''" in col_lower:
                zimag_col = col
        
        if not all([freq_col, zreal_col, zimag_col]):
            print(f"Could not identify required columns in {file_path}")
            print(f"Found - Freq: {freq_col}, Zreal: {zreal_col}, Zimag: {zimag_col}")
            return None
        
        print(f"Matched columns - Freq: {freq_col}, Zreal: {zreal_col}, Zimag: {zimag_col}")
        
        # PANDAS 3.0 COMPATIBILITY: Excel might have comma decimals stored as strings
        # Convert to numeric, handling both formats
        freq_data = df[freq_col]
        zreal_data = df[zreal_col]
        zimag_data = df[zimag_col]
        
        # If any column is object type, replace commas and convert
        for col_name, col_data in [('freq', freq_data), ('zreal', zreal_data), ('zimag', zimag_data)]:
            if col_data.dtype == 'object':
                col_data = col_data.astype(str).str.replace(',', '.')
            
            # Store back after conversion
            if col_name == 'freq':
                freq_data = pd.to_numeric(col_data, errors='coerce')
            elif col_name == 'zreal':
                zreal_data = pd.to_numeric(col_data, errors='coerce')
            else:
                zimag_data = pd.to_numeric(col_data, errors='coerce')
        
        # Remove any NaN values
        valid_mask = ~(freq_data.isna() | zreal_data.isna() | zimag_data.isna())
        
        freq_data = freq_data[valid_mask].reset_index(drop=True)
        zreal_data = zreal_data[valid_mask].reset_index(drop=True)
        zimag_data = zimag_data[valid_mask].reset_index(drop=True)
        
        # Autolab exports -Z'', but we store positive imaginary
        # So negate the column to get positive imaginary
        zimag_data = -zimag_data
        
        # Create time series (just an index, like Gamry does for EIS)
        time_series = pd.Series(range(len(freq_data)), name='index')
        
        # Create ElectrolyzerData object (matching Gamry's EIS pattern)
        data = ElectrolyzerData(
            technique='eis',
            instrument='autolab',
            time=time_series,
            voltage=pd.Series([0] * len(freq_data)),  # EIS doesn't have voltage series
            current=pd.Series([0] * len(freq_data)),  # EIS doesn't have current series
            frequency=freq_data,
            z_real=zreal_data,
            z_imag=zimag_data,
            source_file=file_path
        )
        
        print(f"✓ Loaded Autolab Excel: {file_path.name}")
        print(f"  Shape: {len(data.frequency)} points")
        print(f"  Frequency range: {data.frequency.min():.3f} - {data.frequency.max():.3f} Hz")
        print(f"  Z_real range: {data.z_real.min():.3f} - {data.z_real.max():.3f} Ω")
        print(f"  Z_imag range: {data.z_imag.min():.3f} - {data.z_imag.max():.3f} Ω")
        
        return data
        
    except Exception as e:
        print(f"Error loading Autolab Excel file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_autolab_file(file_path, file_type='auto'):
    """
    Load Autolab file (auto-detect or specify type)
    
    Args:
        file_path: Path to Autolab file
        file_type: 'auto', 'ascii', or 'excel'
        
    Returns:
        ElectrolyzerData object or None if parsing fails
    """
    file_path = Path(file_path)
    
    if file_type == 'auto':
        # Auto-detect based on extension
        if file_path.suffix.lower() == '.txt':
            return load_autolab_ascii(file_path)
        elif file_path.suffix.lower() in ['.xlsx', '.xls']:
            return load_autolab_excel(file_path)
        else:
            print(f"Unknown file type: {file_path.suffix}")
            return None
    elif file_type == 'ascii':
        return load_autolab_ascii(file_path)
    elif file_type == 'excel':
        return load_autolab_excel(file_path)
    else:
        print(f"Unknown file_type: {file_type}")
        return None


def load_autolab_chronopotentiometry_ascii(file_path):
    """
    Load Autolab ASCII chronopotentiometry file (.txt)
    
    Args:
        file_path: Path to .txt file
        
    Returns:
        ElectrolyzerData object or None if parsing fails
    """
    try:
        file_path = Path(file_path)
        
        # Autolab uses tab separator, NOT semicolon for some chrono files
        # Try both separators
        df = None
        for sep in ['\t', ';']:
            try:
                df = pd.read_csv(file_path, sep=sep, encoding='utf-8')
                if len(df.columns) > 1:  # Successfully parsed
                    break
            except Exception:
                continue
        
        if df is None:
            print(f"Could not parse {file_path}")
            return None
        
        # Clean column names
        df.columns = df.columns.str.strip()
        
        print(f"Available columns: {list(df.columns)}")
        
        # Try to identify columns
        # Autolab chronopotentiometry format:
        # Time (s), Corrected time (s), WE(1).Potential (V), WE(1).Current (A), etc.
        
        time_col = None
        voltage_col = None
        current_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            
            # Time
            if 'time' in col_lower and 'corrected' not in col_lower:
                time_col = col
            elif time_col is None and 'time' in col_lower:  # Accept corrected time if no other
                time_col = col
            
            # Voltage/Potential
            if 'potential' in col_lower or 'ewe' in col_lower:
                voltage_col = col
            
            # Current
            if 'current' in col_lower and '<i>' in col_lower:
                current_col = col
            elif current_col is None and 'current' in col_lower:
                current_col = col
            elif current_col is None and 'column 5' in col_lower:
                current_col = col
        
        if not all([time_col, voltage_col, current_col]):
            print(f"Could not identify required columns in {file_path}")
            print(f"Found - Time: {time_col}, Voltage: {voltage_col}, Current: {current_col}")
            return None
        
        print(f"Matched columns - Time: {time_col}, Voltage: {voltage_col}, Current: {current_col}")
        
        # PANDAS 3.0 COMPATIBILITY: Convert to numeric
        time_data = pd.to_numeric(df[time_col], errors='coerce')
        voltage_data = pd.to_numeric(df[voltage_col], errors='coerce')
        current_data = pd.to_numeric(df[current_col], errors='coerce').ffill()
        
        # Remove any NaN values
        valid_mask = ~(time_data.isna() | voltage_data.isna() | current_data.isna())
        
        time_data = time_data[valid_mask].reset_index(drop=True)
        voltage_data = voltage_data[valid_mask].reset_index(drop=True)
        current_data = current_data[valid_mask].reset_index(drop=True)
        
        # Create ElectrolyzerData object
        data = ElectrolyzerData(
            technique='chronopotentiometry',
            instrument='autolab',
            time=time_data,
            voltage=voltage_data,
            current=current_data,
            source_file=file_path
        )
        
        print(f"✓ Loaded Autolab ASCII chronopotentiometry: {file_path.name}")
        print(f"  Shape: {len(data.time)} points")
        print(f"  Time range: {data.time.min():.2f} - {data.time.max():.2f} s")
        print(f"  Voltage range: {data.voltage.min():.3f} - {data.voltage.max():.3f} V")
        print(f"  Current range: {data.current.min():.6f} - {data.current.max():.6f} A")
        
        return data
        
    except Exception as e:
        print(f"Error loading Autolab ASCII chronopotentiometry file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None


def load_autolab_chronopotentiometry_excel(file_path):
    """
    Load Autolab Excel chronopotentiometry file (.xlsx)
    
    Args:
        file_path: Path to .xlsx file
        
    Returns:
        ElectrolyzerData object or None if parsing fails
    """
    try:
        file_path = Path(file_path)
        
        # Read the Excel file (first sheet)
        df = pd.read_excel(file_path, sheet_name=0)
        
        # Clean column names
        df.columns = df.columns.str.strip()
        
        print(f"Available columns: {list(df.columns)}")
        
        # Try to identify columns
        time_col = None
        voltage_col = None
        current_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            
            # Time
            if 'time' in col_lower and 'corrected' not in col_lower:
                time_col = col
            elif time_col is None and 'time' in col_lower:
                time_col = col
            
            # Voltage/Potential
            if 'potential' in col_lower or 'ewe' in col_lower:
                voltage_col = col
            
            # Current
            if 'current' in col_lower and '<i>' in col_lower:
                current_col = col
            elif current_col is None and 'current' in col_lower:
                current_col = col
        
        if not all([time_col, voltage_col, current_col]):
            print(f"Could not identify required columns in {file_path}")
            print(f"Found - Time: {time_col}, Voltage: {voltage_col}, Current: {current_col}")
            return None
        
        print(f"Matched columns - Time: {time_col}, Voltage: {voltage_col}, Current: {current_col}")
        
        # PANDAS 3.0 COMPATIBILITY: Handle comma decimals if present
        time_data = df[time_col]
        voltage_data = df[voltage_col]
        current_data = df[current_col]
        
        # If any column is object type (string), replace commas and convert
        for col_name, col_data in [('time', time_data), ('voltage', voltage_data), ('current', current_data)]:
            if col_data.dtype == 'object':
                col_data = col_data.astype(str).str.replace(',', '.')
            
            # Convert to numeric
            if col_name == 'time':
                time_data = pd.to_numeric(col_data, errors='coerce')
            elif col_name == 'voltage':
                voltage_data = pd.to_numeric(col_data, errors='coerce')
            else:
                current_data = pd.to_numeric(col_data, errors='coerce')
        
        # Remove any NaN values
        valid_mask = ~(time_data.isna() | voltage_data.isna() | current_data.isna())
        
        time_data = time_data[valid_mask].reset_index(drop=True)
        voltage_data = voltage_data[valid_mask].reset_index(drop=True)
        current_data = current_data[valid_mask].reset_index(drop=True)
        
        # Create ElectrolyzerData object
        data = ElectrolyzerData(
            technique='chronopotentiometry',
            instrument='autolab',
            time=time_data,
            voltage=voltage_data,
            current=current_data,
            source_file=file_path
        )
        
        print(f"✓ Loaded Autolab Excel chronopotentiometry: {file_path.name}")
        print(f"  Shape: {len(data.time)} points")
        print(f"  Time range: {data.time.min():.2f} - {data.time.max():.2f} s")
        print(f"  Voltage range: {data.voltage.min():.3f} - {data.voltage.max():.3f} V")
        print(f"  Current range: {data.current.min():.6f} - {data.current.max():.6f} A")
        
        return data
        
    except Exception as e:
        print(f"Error loading Autolab Excel chronopotentiometry file {file_path}: {e}")
        import traceback
        traceback.print_exc()
        return None