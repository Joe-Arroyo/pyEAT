"""
Gamry potentiostat file parser - PANDAS 3.0 COMPATIBLE
Properly handles European decimal format and pandas 3.x strict conversions
"""

import pandas as pd
import os
from pathlib import Path
from typing import Optional
import sys

# Add parent directory to path to import core modules
sys.path.append(str(Path(__file__).parent.parent))
from core.data_model import ElectrolyzerData


class GamryParser:
    """Parser for Gamry .DTA files"""
    
    @staticmethod
    def read_dta(filepath: str) -> Optional[pd.DataFrame]:
        """
        Read Gamry .DTA files and return clean pandas DataFrame.
        
        Parameters:
        -----------
        filepath : str
            Path to the .DTA file
        
        Returns:
        --------
        pandas.DataFrame or None
            Electrochemical data with columns like T, Vf, Im, Freq, Zreal, Zimag
        """
        
        if not os.path.exists(filepath):
            print(f"❌ File not found: {filepath}")
            return None
        
        try:
            # Read the file ONCE. Opening the file a second time is wasteful in
            # general and expensive for cloud-backed storage (e.g. OneDrive
            # Files On-Demand), where every open can trigger a fresh download.
            encodings = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
            text = None

            for encoding in encodings:
                try:
                    with open(filepath, 'r', encoding=encoding, errors='ignore') as file:
                        text = file.read()
                    break
                except UnicodeDecodeError:
                    continue

            if text is None:
                print("❌ Could not read file with any encoding")
                return None

            lines = text.splitlines()

            # Find the data section (usually starts after CURVE or similar)
            data_start = 0
            for i, line in enumerate(lines):
                if 'Pt' in line and ('V' in line or 'mV' in line):
                    data_start = i
                    break

            # Parse the already-loaded text (no second read of the file).
            # low_memory=False parses each column in one pass, which avoids the
            # mixed-type DtypeWarning and the slow chunked type inference.
            from io import StringIO
            try:
                df = pd.read_csv(StringIO(text),
                                 sep='\t',
                                 skiprows=data_start,
                                 on_bad_lines='skip',
                                 low_memory=False)
            except pd.errors.ParserError:
                print("❌ Could not parse data")
                return None

            if df is None:
                print("❌ Could not parse data with any encoding")
                return None
            
            # Clean column names
            df.columns = df.columns.str.strip()
            
            # CRITICAL FIX: Remove the first row if it contains units
            # Check if first row has non-numeric text like 's', 'V', 'A'
            first_row_values = df.iloc[0].astype(str).values
            if any(val in ['s', 'V', 'A', 'Hz', 'Ohm', 'V vs. Ref.'] for val in first_row_values):
                df = df.iloc[1:].reset_index(drop=True)
                print(f"  ℹ️  Removed units row")
            
            # PANDAS 3.0 COMPATIBILITY FIX
            # Must do comma replacement and numeric conversion in TWO SEPARATE steps
            
            # STEP 1: Convert European format (comma → dot) for ALL object columns
            # This handles Spanish/European locale where decimals use comma: 1,5 instead of 1.5
            for col in df.columns:
                if pd.api.types.is_string_dtype(df[col]) or pd.api.types.is_object_dtype(df[col]):
                    df[col] = df[col].astype(str).str.replace(',', '.')
            
            # STEP 2: Convert to numeric (after comma replacement is complete)
            # Using errors='coerce' converts invalid values to NaN instead of raising errors
            for col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                except (ValueError, TypeError):
                    pass  # Keep as text if conversion fails
            
            print(f"✓ Loaded {os.path.basename(filepath)}")
            print(f"  Shape: {df.shape[0]} points, {df.shape[1]} columns")
            print(f"  Columns: {list(df.columns)}")
            
            return df
            
        except Exception as e:
            print(f"❌ Error reading {filepath}")
            print(f"Error: {e}")
            return None
    
    @staticmethod
    def detect_technique(df: pd.DataFrame) -> str:
        """
        Detect if the data is polarization, EIS, or chronopotentiometry
        
        Parameters:
        -----------
        df : pd.DataFrame
            Data read from Gamry file
        
        Returns:
        --------
        str : 'polarization', 'eis', or 'chronopotentiometry'
        """
        columns_lower = [col.lower() for col in df.columns]
        
        # Check for EIS data
        if any('freq' in col for col in columns_lower) and \
           any('zreal' in col for col in columns_lower):
            return 'eis'
        
        # Check for polarization/chronopotentiometry
        # Both have T, Vf, Im - we default to chronopotentiometry for now
        # GUI will let user choose or we can add more logic later
        if any('vf' in col or 'v' in col for col in columns_lower) and \
           any('im' in col or 'i' in col for col in columns_lower):
            return 'chronopotentiometry'
        
        return 'unknown'
    
    @staticmethod
    def to_electrolyzer_data(filepath: str, technique: str = None) -> Optional[ElectrolyzerData]:
        """
        Read Gamry file and convert to unified ElectrolyzerData format
        
        Parameters:
        -----------
        filepath : str
            Path to .DTA file
        technique : str, optional
            Force a specific technique ('eis', 'polarization', 'chronopotentiometry')
            If None, auto-detect
        
        Returns:
        --------
        ElectrolyzerData or None
        """
        # Read the raw data
        df = GamryParser.read_dta(filepath)
        if df is None:
            return None
        
        # Detect or use provided technique
        if technique is None:
            technique = GamryParser.detect_technique(df)
        
        if technique == 'eis':
            return GamryParser._parse_eis(df, filepath)
        elif technique in ['polarization', 'chronopotentiometry']:
            return GamryParser._parse_polarization(df, filepath, technique)
        else:
            print(f"❌ Unknown technique type: {technique}")
            return None
    
    @staticmethod
    def _parse_polarization(df: pd.DataFrame, filepath: str, technique: str) -> ElectrolyzerData:
        """Parse polarization curve or chronopotentiometry data"""
        
        # Find column names (case-insensitive)
        time_col = None
        voltage_col = None
        current_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            if col_lower == 't' or 'time' in col_lower:
                time_col = col
            if col_lower == 'vf' or 'voltage' in col_lower or col_lower == 'v':
                voltage_col = col
            if col_lower == 'im' or 'current' in col_lower or col_lower == 'i':
                current_col = col
        
        if not all([time_col, voltage_col, current_col]):
            raise ValueError(f"Missing required columns. Found: {df.columns.tolist()}")
        
        # Create ElectrolyzerData object with properly converted numeric data
        return ElectrolyzerData(
            technique=technique,
            instrument='gamry',
            time=pd.to_numeric(df[time_col], errors='coerce'),
            voltage=pd.to_numeric(df[voltage_col], errors='coerce'),
            current=pd.to_numeric(df[current_col], errors='coerce'),
            source_file=Path(filepath)
        )
    
    @staticmethod
    def _parse_eis(df: pd.DataFrame, filepath: str) -> ElectrolyzerData:
        """Parse EIS data"""
        
        # Find column names (case-insensitive)
        freq_col = None
        zreal_col = None
        zimag_col = None
        
        for col in df.columns:
            col_lower = col.lower()
            if 'freq' in col_lower:
                freq_col = col
            if 'zreal' in col_lower:
                zreal_col = col
            if 'zimag' in col_lower:
                zimag_col = col
        
        if not all([freq_col, zreal_col, zimag_col]):
            raise ValueError(f"Missing required EIS columns. Found: {df.columns.tolist()}")
        
        # For EIS, time is not critical, we can use frequency as index
        time_series = pd.Series(range(len(df)), name='index')
        
        # Data is already converted to numeric in read_dta()
        zreal_numeric = pd.to_numeric(df[zreal_col], errors='coerce')
        zimag_numeric = pd.to_numeric(df[zimag_col], errors='coerce')
        freq_numeric = pd.to_numeric(df[freq_col], errors='coerce')
        
        # Remove NaN values
        valid_mask = ~(zreal_numeric.isna() | zimag_numeric.isna() | freq_numeric.isna())
        
        # Create ElectrolyzerData object
        return ElectrolyzerData(
            technique='eis',
            instrument='gamry',
            time=time_series[valid_mask].reset_index(drop=True),
            voltage=pd.Series([0] * valid_mask.sum()),  # EIS doesn't have voltage series
            current=pd.Series([0] * valid_mask.sum()),  # EIS doesn't have current series
            frequency=freq_numeric[valid_mask].reset_index(drop=True),
            z_real=zreal_numeric[valid_mask].reset_index(drop=True),
            z_imag=zimag_numeric[valid_mask].reset_index(drop=True),
            source_file=Path(filepath)
        )


# Convenience function
def load_gamry_file(filepath: str, technique: str = None) -> Optional[ElectrolyzerData]:
    """
    Quick function to load a Gamry file
    
    Usage:
        data = load_gamry_file('my_experiment.DTA')
        data = load_gamry_file('my_experiment.DTA', technique='polarization')
    """
    return GamryParser.to_electrolyzer_data(filepath, technique)