from openpyxl import load_workbook
import warnings
from typing import Generator
from .models import ParsedVocabularyEntry

def parse_workbook(filepath: str, schema: str) -> Generator[ParsedVocabularyEntry, None, None]:
    warnings.simplefilter("ignore")
    wb = load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active
    
    row_idx = 1
    order = 1
    for row in ws.iter_rows(values_only=True):
        raw_values = {f"col_{i}": val for i, val in enumerate(row) if val is not None}
        if not raw_values:
            row_idx += 1
            continue
            
        term = ""
        meaning = ""
        phonetic_uk = None
        phonetic_us = None
        pos = None
        
        if schema == "SCHEMA_HEADERLESS":
            if len(row) >= 2:
                term = str(row[0]).strip() if row[0] else ""
                meaning = str(row[1]).strip() if row[1] else ""
                
        elif schema in ["SCHEMA_B", "SCHEMA_A"]:
            if row_idx == 1:
                row_idx += 1
                continue # Skip header
            
            # Simple fallback for now: just map col 0 and 1, we can refine based on header indices
            if len(row) >= 2:
                term = str(row[0]).strip() if row[0] else ""
                meaning = str(row[1]).strip() if row[1] else ""
                if len(row) > 2:
                    phonetic_uk = str(row[2]).strip() if row[2] else None
                if len(row) > 3:
                    phonetic_us = str(row[3]).strip() if row[3] else None
        
        if term and not term.isdigit() and len(term) < 100:
            yield ParsedVocabularyEntry(
                term=term,
                phonetic_uk=phonetic_uk,
                phonetic_us=phonetic_us,
                phonetic_generic=None,
                definition_raw=meaning,
                pos=pos,
                sentence=None,
                source_row=row_idx,
                source_order=order,
                raw_values=raw_values
            )
            order += 1
            
        row_idx += 1

