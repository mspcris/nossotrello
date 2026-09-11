# boards/services/sheet_preview.py
"""Prévia de planilha (XLSX/XLSM/CSV) para o visualizador do card.

Clicar num .xlsx anexado baixava o arquivo — quem só queria conferir o
conteúdo ficava com um download a cada olhada. Aqui o servidor lê a planilha
e devolve linhas prontas para montar uma tabela HTML; o download continua
disponível no botão do visualizador.

Leitura é sempre limitada: prévia, não editor. Planilha maior que os limites
vem cortada, com `truncated` avisando a tela.
"""
import csv
import io
import logging
from datetime import date, datetime, time

logger = logging.getLogger(__name__)

SUPPORTED = ("xlsx", "xlsm", "csv", "tsv", "txt")
MAX_SHEETS = 12
MAX_ROWS = 500
MAX_COLS = 60
MAX_CELL_CHARS = 300


def is_supported(ext: str) -> bool:
    return (ext or "").lower().lstrip(".") in SUPPORTED


def _fmt(v) -> str:
    """Valor da célula como o brasileiro lê: data dd/mm/aaaa, decimal com vírgula."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "VERDADEIRO" if v else "FALSO"
    if isinstance(v, datetime):
        # openpyxl devolve datetime mesmo para célula só-data
        if v.hour or v.minute or v.second:
            return v.strftime("%d/%m/%Y %H:%M")
        return v.strftime("%d/%m/%Y")
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, time):
        return v.strftime("%H:%M")
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.4f}".rstrip("0").rstrip(".").replace(".", ",")
    s = str(v)
    return s[:MAX_CELL_CHARS] + "…" if len(s) > MAX_CELL_CHARS else s


def _trim(rows: list) -> list:
    """Tira colunas e linhas totalmente vazias das bordas."""
    while rows and not any(c.strip() for c in rows[-1]):
        rows.pop()
    if not rows:
        return []
    width = 0
    for r in rows:
        for i, c in enumerate(r):
            if c.strip():
                width = max(width, i + 1)
    return [r[:width] + [""] * max(0, width - len(r[:width])) for r in rows]


def _read_xlsx(data: bytes) -> list:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets[:MAX_SHEETS]:
            rows, truncated = [], False
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= MAX_ROWS:
                    truncated = True
                    break
                cells = [_fmt(v) for v in row[:MAX_COLS]]
                if len(row) > MAX_COLS:
                    truncated = True
                rows.append(cells)
            sheets.append({"title": ws.title or "Planilha", "rows": _trim(rows), "truncated": truncated})
    finally:
        try:
            wb.close()
        except Exception:
            pass
    return sheets


def _read_csv(data: bytes, title: str) -> list:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
        delim = dialect.delimiter
    except Exception:
        # CSV brasileiro costuma sair do Excel com ponto e vírgula
        delim = ";" if sample.count(";") > sample.count(",") else ","

    rows, truncated = [], False
    for i, row in enumerate(csv.reader(io.StringIO(text), delimiter=delim)):
        if i >= MAX_ROWS:
            truncated = True
            break
        cells = [_fmt(c) for c in row[:MAX_COLS]]
        if len(row) > MAX_COLS:
            truncated = True
        rows.append(cells)
    return [{"title": title or "Planilha", "rows": _trim(rows), "truncated": truncated}]


def read(fieldfile, ext: str, title: str = "") -> dict:
    """{'sheets': [...]} ou {'error': 'mensagem'}."""
    ext = (ext or "").lower().lstrip(".")
    if not is_supported(ext):
        return {"error": "Este formato não abre na prévia — use o botão de baixar."}

    try:
        fieldfile.open("rb")
        try:
            data = fieldfile.read()
        finally:
            try:
                fieldfile.close()
            except Exception:
                pass
    except Exception:
        logger.exception("sheet_preview: não consegui ler os bytes do anexo")
        return {"error": "Não foi possível ler o arquivo no servidor."}

    if not data:
        return {"error": "O arquivo está vazio ou não existe mais no servidor."}

    try:
        sheets = _read_xlsx(data) if ext in ("xlsx", "xlsm") else _read_csv(data, title)
    except Exception:
        logger.exception("sheet_preview: falha ao interpretar %s", ext)
        return {"error": "Não consegui interpretar a planilha — baixe o arquivo para abrir no Excel."}

    sheets = [s for s in sheets if s["rows"]] or sheets
    if not sheets:
        return {"error": "A planilha não tem conteúdo para mostrar."}
    return {"sheets": sheets}
