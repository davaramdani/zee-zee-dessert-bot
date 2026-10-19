# sheets_sync.py
import os
from datetime import datetime
from google.oauth2.service_account import Credentials
import gspread

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

SPREADSHEET_ID = os.environ.get('GOOGLE_SHEETS_ID', '').strip()
WORKSHEET_NAME = os.environ.get('GOOGLE_SHEETS_WORKSHEET', 'Pesanan').strip()
SERVICE_ACCOUNT_FILE = os.environ.get('GOOGLE_SERVICE_ACCOUNT_FILE', 'google_service_account.json').strip()

HEADERS = [
    'order_id',
    'created_at',
    'updated_at',
    'user_id',
    'nama_pemesan',
    'alamat',
    'items',
    'total',
    'status_pembayaran',
    'pengirim_transfer',
    'nominal_transfer',
]


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _get_client():
    if not SPREADSHEET_ID:
        raise ValueError('GOOGLE_SHEETS_ID belum diset di .env')
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        raise FileNotFoundError(
            f'File service account tidak ditemukan: {SERVICE_ACCOUNT_FILE}'
        )

    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )
    return gspread.authorize(creds)


def _get_worksheet():
    gc = _get_client()
    sh = gc.open_by_key(SPREADSHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=1000, cols=20)
        ws.append_row(HEADERS)
    else:
        current_headers = ws.row_values(1)
        if current_headers != HEADERS:
            if not current_headers:
                ws.append_row(HEADERS)
            else:
                ws.update('A1:K1', [HEADERS])
    return ws


def _order_items_to_text(order):
    if not getattr(order, 'items', None):
        return ''
    lines = []
    for i, item in enumerate(order.items, 1):
        tanggal = getattr(item, 'tanggal_antar', '') or '-'
        lines.append(
            f"{i}. {item.nama} x{item.jumlah} | tgl: {tanggal} | harga: Rp {item.harga_satuan:,}"
        )
    return ' || '.join(lines)


def _build_row(user_id: str, order, status_pembayaran: str, pengirim_transfer: str = '', nominal_transfer: int = 0):
    now = _now_str()
    return [
        user_id,
        now,
        now,
        user_id,
        getattr(order, 'nama_pemesan', '') or '',
        getattr(order, 'alamat', '') or '',
        _order_items_to_text(order),
        getattr(order, 'total', 0) or 0,
        status_pembayaran,
        pengirim_transfer or '',
        nominal_transfer or 0,
    ]


def _find_row_by_order_id(ws, order_id: str):
    values = ws.col_values(1)
    for idx, value in enumerate(values, start=1):
        if str(value).strip() == str(order_id).strip():
            return idx
    return None


def upsert_order_to_sheet(user_id: str, order, status_pembayaran: str = 'menunggu pembayaran', pengirim_transfer: str = '', nominal_transfer: int = 0):
    ws = _get_worksheet()
    row = _build_row(user_id, order, status_pembayaran, pengirim_transfer, nominal_transfer)
    existing_row = _find_row_by_order_id(ws, user_id)

    if existing_row and existing_row > 1:
        row[1] = ws.cell(existing_row, 2).value or row[1]
        row[2] = _now_str()
        ws.update(f'A{existing_row}:K{existing_row}', [row])
        return existing_row
    else:
        ws.append_row(row)
        return ws.row_count


def mark_order_paid(user_id: str, order, pengirim_transfer: str = '', nominal_transfer: int = 0):
    return upsert_order_to_sheet(
        user_id=user_id,
        order=order,
        status_pembayaran='pembayaran sukses',
        pengirim_transfer=pengirim_transfer,
        nominal_transfer=nominal_transfer,
    )
