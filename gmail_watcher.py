# gmail_watcher.py
import os
import base64
import re
import time
import threading
from html import unescape
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build


SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


# ─────────────────────────────────────────────
# FILTER: Subject email penerimaan uang
# ─────────────────────────────────────────────
SUBJECT_TERIMA = [
    "menerima sejumlah uang",
    "menerima uang di jago",
    "kamu telah menerima",
    "asik, kamu telah menerima",
]


DAFTAR_BANK = (
    r'Seabank|ShopeePay|GoPay|Gopay|BCA|BNI|BRI|Mandiri|OVO|Dana|'
    r'LinkAja|Jenius|Flip|CIMB|Permata|Danamon|BSI|OCBC|Blu|'
    r'Neo|Neobank|Allo|Amar|Bank\s+Raya|Jago'
)


def is_email_penerimaan(subject: str) -> bool:
    s = (subject or "").lower()
    return any(k in s for k in SUBJECT_TERIMA)


# ─────────────────────────────────────────────
# SETUP: Autentikasi Gmail
# ─────────────────────────────────────────────
def get_gmail_service():
    creds = None

    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except Exception:
                creds = None

        if not creds or not creds.valid:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=8080)

        with open("token.json", "w", encoding="utf-8") as token:
            token.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)


# ─────────────────────────────────────────────
# HELPER: Ekstrak body email (plain/html)
# ─────────────────────────────────────────────
def extract_email_body(payload: dict) -> str:
    plain_body = ""
    html_body = ""

    def _extract(part):
        nonlocal plain_body, html_body

        mime = part.get("mimeType", "")
        if mime.startswith("multipart"):
            for child in part.get("parts", []):
                _extract(child)
            return

        data = part.get("body", {}).get("data", "")
        if not data:
            return

        try:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="ignore")
        except Exception:
            decoded = ""

        if mime == "text/plain" and decoded and not plain_body:
            plain_body = decoded
        elif mime == "text/html" and decoded and not html_body:
            html_body = decoded

    _extract(payload)

    if plain_body.strip():
        return re.sub(r"\s+", " ", plain_body).strip()

    if html_body:
        text = re.sub(r"<style[^>]*>.*?</style>", " ", html_body, flags=re.I | re.S)
        text = re.sub(r"<script[^>]*>.*?</script>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<head[^>]*>.*?</head>", " ", text, flags=re.I | re.S)
        text = re.sub(r"<[^>]+>", " ", text)
        text = unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    return ""


# ─────────────────────────────────────────────
# PARSER: Nominal
# ─────────────────────────────────────────────
def parse_nominal(body: str):
    patterns = [
        r'Jumlah\s*[:\-]?\s*Rp\s*([\d.,]+)',
        r'menerima\s+Rp\s*([\d.,]+)',
        r'sebesar\s+Rp\s*([\d.,]+)',
        r'senilai\s+Rp\s*([\d.,]+)',
        r'diterima\s+Rp\s*([\d.,]+)',
        r'Rp\s*([\d.,]+)',
    ]

    clean_body = re.sub(r"\s+", " ", body)

    for pattern in patterns:
        match = re.search(pattern, clean_body, re.IGNORECASE)
        if match:
            raw = match.group(1)
            digits = re.sub(r"[^\d]", "", raw)

            if digits:
                nominal = int(digits)
                if nominal >= 1000:
                    return nominal

    return None


# ─────────────────────────────────────────────
# PARSER: Pengirim
# ─────────────────────────────────────────────
def parse_pengirim(subject: str, body: str) -> str:
    m = re.search(r'dari\s+([A-Za-z0-9]+(?:\s+[A-Za-z0-9]+)?)\s*$', subject or "", re.IGNORECASE)
    if m:
        return m.group(1).strip()

    m = re.search(
        r'Dari\s+(.{3,60}?)\s+(?:' + DAFTAR_BANK + r')\s*[•·]?\s*\d+',
        body,
        re.IGNORECASE
    )
    if m:
        candidate = re.sub(r"\s+", " ", m.group(1)).strip(" .:-")
        if candidate:
            return candidate.title()

    m = re.search(
        r'Dari\s+([A-Z][A-Z\s]{3,40}?)\s+(?:' + DAFTAR_BANK + r')',
        body
    )
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip().title()

    return "Customer"


# ─────────────────────────────────────────────
# PARSER: Baca nominal & pengirim dari email
# ─────────────────────────────────────────────
def parse_bank_jago_email(subject: str, body: str) -> dict:
    return {
        "nominal": parse_nominal(body),
        "pengirim": parse_pengirim(subject, body)
    }


# ─────────────────────────────────────────────
# WATCHER: Monitor Gmail setiap N detik
# ─────────────────────────────────────────────
def watch_gmail_for_payment(callback, check_interval: int = 30):
    service = get_gmail_service()
    seen_ids = set()

    print("📧 Gmail watcher aktif — memantau transfer masuk Bank Jago...")
    print(f"⏱️  Interval pengecekan: setiap {check_interval} detik\n")

    while True:
        try:
            # PERBAIKAN: tidak lagi memakai "is:unread" karena email yang
            # sudah terbuka/dibaca manual (misal untuk screenshot debug)
            # tidak akan pernah muncul lagi di query is:unread.
            # Sekarang memakai rentang waktu + seen_ids untuk mencegah duplikat.
            results = service.users().messages().list(
                userId="me",
                q="from:noreply@jago.com newer_than:1d",
                maxResults=10
            ).execute()

            messages = results.get("messages", [])

            if messages:
                print(f"📬 {len(messages)} email dari Bank Jago (1 hari terakhir)")

            for msg in messages:
                msg_id = msg["id"]

                if msg_id in seen_ids:
                    continue
                seen_ids.add(msg_id)

                message = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full"
                ).execute()

                headers = message.get("payload", {}).get("headers", [])
                subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
                sender = next((h["value"] for h in headers if h["name"] == "From"), "")

                print(f"\n📨 Email baru:")
                print(f"   From   : {sender}")
                print(f"   Subject: {subject}")

                if not is_email_penerimaan(subject):
                    print("   ⏭️  Skip — bukan email penerimaan uang\n")
                    continue

                body = extract_email_body(message.get("payload", {}))

                if not body:
                    print("   ⚠️  Body kosong, skip.\n")
                    continue

                print(f"   Preview: {body[:150]}...")

                payment_info = parse_bank_jago_email(subject, body)

                if payment_info["nominal"]:
                    nominal = payment_info["nominal"]
                    pengirim = payment_info["pengirim"]

                    print("\n✅ TRANSFER TERDETEKSI!")
                    print(f"   Nominal  : Rp {nominal:,}")
                    print(f"   Pengirim : {pengirim}\n")

                    callback(nominal, pengirim)
                else:
                    print("   ⚠️  Nominal tidak terbaca.")
                    print(f"   Body:\n   {body[:400]}\n")

        except Exception as e:
            print(f"❌ Error Gmail watcher: {e}")

        time.sleep(check_interval)


# ─────────────────────────────────────────────
# THREAD: Jalankan di background
# ─────────────────────────────────────────────
def start_gmail_watcher_thread(callback, check_interval: int = 30):
    thread = threading.Thread(
        target=watch_gmail_for_payment,
        args=(callback, check_interval),
        daemon=True
    )
    thread.start()
    print("🧵 Gmail watcher thread dimulai di background.")
    return thread


# ─────────────────────────────────────────────
# DEBUG: Test langsung tanpa bot
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("🔍 Mode debug — cek 5 email Bank Jago terbaru\n")

    service = get_gmail_service()
    results = service.users().messages().list(
        userId="me",
        q="from:noreply@jago.com",
        maxResults=5
    ).execute()

    messages = results.get("messages", [])

    if not messages:
        print("❌ Tidak ada email dari Bank Jago ditemukan.")
    else:
        print(f"✅ Ditemukan {len(messages)} email Bank Jago\n")

        for i, msg in enumerate(messages, 1):
            message = service.users().messages().get(
                userId="me",
                id=msg["id"],
                format="full"
            ).execute()

            headers = message.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers if h["name"] == "Subject"), "")
            sender = next((h["value"] for h in headers if h["name"] == "From"), "")
            body = extract_email_body(message.get("payload", {}))

            print(f"── Email #{i} ──────────────────────────────────")
            print(f"From   : {sender}")
            print(f"Subject: {subject}")
            print(f"Preview: {body[:200]}")

            if not is_email_penerimaan(subject):
                print("Status : ⏭️  SKIP — bukan email penerimaan uang")
                print()
                continue

            payment_info = parse_bank_jago_email(subject, body)

            print("\nHasil parse:")
            if payment_info["nominal"]:
                print(f"  ✅ Nominal  : Rp {payment_info['nominal']:,}")
            else:
                print("  ❌ Nominal  : Tidak terdeteksi")

            print(f"  Pengirim   : {payment_info['pengirim'] or '❌ Tidak terdeteksi'}")
            print()
