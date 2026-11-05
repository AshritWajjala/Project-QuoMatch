from datetime import date, datetime
from pathlib import Path
from typing import Tuple, Union
import openpyxl
import xlrd
import pandas as pd
from openpyxl.worksheet.worksheet import Worksheet

from app.core.exceptions import QuoMatchException
from app.core.logger import setup_logger

logger = setup_logger()


class ExcelIngestion:
    """Ingestion service for Excel (.xlsx, .xls) files.

    Loads the active worksheet, calculates data bounding boxes to trim
    unpopulated margins, and serializes cells into a normalized pipe-delimited grid.
    """

    @staticmethod
    def load_active_sheet(excel_path: Union[str, Path]) -> Worksheet:
        """Loads the active worksheet with evaluated cached formula results.

        Args:
            excel_path (Union[str, Path]): Path to the target Excel file.

        Returns:
            Worksheet: The active openpyxl worksheet object.

        Raises:
            QuoMatchException: If the file does not exist or fails to load.
        """
        path = Path(excel_path)
        if not path.exists():
            logger.error("Excel file not found at path: %s", path.resolve())
            raise QuoMatchException(f"Excel file not found: {path.resolve()}")

        try:
            target_path = path
            
            # Handle old .xls format by converting it to .xlsx in-memory via pandas & xlrd
            if path.suffix.lower() == ".xls":
                df = pd.read_excel(path, sheet_name=0, engine="xlrd")
                target_path = path.with_suffix(".xlsx")
                df.to_excel(target_path, index=False, engine="openpyxl")
                
            # data_only=True evaluates and returns cached formula results
            wb = openpyxl.load_workbook(filename=path, data_only=True)
            return wb.active
        except Exception as e:
            logger.error("Failed to load Excel sheet from %s: %s", path.resolve(), e)
            raise QuoMatchException(f"Error loading Excel workbook: {e}") from e

    @staticmethod
    def find_data_bounds(sheet: Worksheet) -> Tuple[int, int, int, int]:
        """Calculates the bounding box coordinates containing non-empty cells.

        Trims leading, trailing, and margin dead space.

        Args:
            sheet (Worksheet): The active openpyxl worksheet.

        Returns:
            Tuple[int, int, int, int]: Bounding box (min_row, max_row, min_col, max_col).
        """
        min_r, max_r = None, None
        min_c, max_c = None, None

        for r in range(1, sheet.max_row + 1):
            for c in range(1, sheet.max_column + 1):
                val = sheet.cell(row=r, column=c).value
                if val is not None and str(val).strip() != "":
                    if min_r is None or r < min_r:
                        min_r = r
                    if max_r is None or r > max_r:
                        max_r = r
                    if min_c is None or c < min_c:
                        min_c = c
                    if max_c is None or c > max_c:
                        max_c = c

        # Fallback if the sheet has no content
        if min_r is None:
            return 1, 1, 1, 1

        return min_r, max_r, min_c, max_c

    @classmethod
    def convert_excel_to_markdown(cls, excel_path: Union[str, Path]) -> str:
        """Converts an active sheet of an Excel workbook into a clean Markdown table string.

        This method loads the active sheet, determines data boundaries, handles formatting 
        for dates and numeric values, escapes special characters like pipes and newlines, 
        and dynamically truncates the table width based on header detection to strip 
        extraneous right-hand columns.

        Args:
            excel_path (Union[str, Path]): The file path to the Excel workbook to be converted.

        Returns:
            str: A formatted multi-line string representing the table in Markdown format.
        """
        sheet = cls.load_active_sheet(excel_path=excel_path)
        min_r, max_r, min_c, max_c = cls.find_data_bounds(sheet)

        raw_rows = []
        for r in range(min_r, max_r + 1):
            row_vals = []
            for c in range(min_c, max_c + 1):
                val = sheet.cell(row=r, column=c).value
                if val is not None and str(val).strip() != "":
                    if isinstance(val, (datetime, date)):
                        text = val.strftime("%Y-%m-%d")
                    elif isinstance(val, float) and val.is_integer():
                        text = str(int(val))
                    else:
                        text = str(val).strip()
                    text = text.replace("\n", " ").replace("|", "/")
                    row_vals.append(text)
                else:
                    row_vals.append("")
            raw_rows.append(row_vals)

        # 1. Detect the column width of the real customer table
        # We find the table header row and stop at its last non-empty column
        table_width = None
        for row in raw_rows:
            row_str_lower = " ".join(row).lower()
            if "part no" in row_str_lower or "total cost" in row_str_lower or "qty" in row_str_lower:
                for idx in range(len(row) - 1, -1, -1):
                    if row[idx] != "":
                        table_width = idx + 1
                        break
                break

        # 2. Slice rows to table_width and strip dead right-hand empty cells
        lines = []
        for row in raw_rows:
            clean_row = row[:table_width] if table_width else row
            while clean_row and clean_row[-1] == "":
                clean_row.pop()

            if clean_row:
                lines.append("| " + " | ".join(clean_row) + " |")

        return "\n".join(lines)