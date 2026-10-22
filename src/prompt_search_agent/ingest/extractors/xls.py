from pathlib import Path

import xlrd

from prompt_search_agent.ingest.extractors.xlsx import MIN_PROMPT_LENGTH
from prompt_search_agent.ingest.records import RawPromptRecord


class XlsPromptExtractor:
    def extract(self, path: Path) -> list[RawPromptRecord]:
        rps: list[RawPromptRecord] = []
        workbook = xlrd.open_workbook(
            filename=str(path),
            on_demand=True,
        )

        try:
            for worksheet in workbook.sheets():
                if worksheet.name.startswith("WpsReserved_"):
                    continue

                for row_index in range(worksheet.nrows):
                    row_values = worksheet.row_values(row_index)

                    for value in row_values:
                        if value is None:
                            continue

                        prompt_text = str(value).strip()

                        if not prompt_text:
                            continue

                        if prompt_text.startswith("="):
                            continue

                        if len(prompt_text) < MIN_PROMPT_LENGTH:
                            continue

                        rps.append(
                            RawPromptRecord(
                                prompt_text=prompt_text,
                                category=path.stem,
                                source_file=path.name,
                                source_sheet=worksheet.name,
                                source_row=row_index + 1,
                            )
                        )
        finally:
            workbook.release_resources()
        return rps
