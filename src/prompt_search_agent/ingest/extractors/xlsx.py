from pathlib import Path

from openpyxl import load_workbook

from prompt_search_agent.ingest.records import RawPromptRecord

MIN_PROMPT_LENGTH = 20
class XlsxPromptExtractor:
    def extract(self, path: Path) -> list[RawPromptRecord]:
        wb = load_workbook(
            filename=path,
            read_only=True,
            data_only=True,
        )
        rps : list[RawPromptRecord] = []
        try:
            for worksheet in wb.worksheets:
                if worksheet.title.startswith("WpsReserved_"):
                    continue

                for row_number, row in enumerate(
                        worksheet.iter_rows(values_only=True),
                        start=1,
                ):
                    for val in row:
                        if val is None:
                            continue

                        s = str(val).strip()

                        if not s:
                            continue

                        if s.startswith("="):
                            continue

                        if len(s) < MIN_PROMPT_LENGTH:
                            continue

                        rp = RawPromptRecord(
                            prompt_text=s,
                            category=path.stem,
                            source_file=path.name,
                            source_sheet=worksheet.title,
                            source_row=row_number,
                        )
                        rps.append(rp)

                    # 当前行处理结束
        finally:
            wb.close()
        return rps

