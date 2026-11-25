# auth_gmail.py — jalankan untuk otorisasi awal atau login ulang Gmail
from pathlib import Path
from google.auth.exceptions import RefreshError
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_FILE = Path("token.json")


class GmailAuthorizationRequired(RuntimeError):
    pass


def load_gmail_credentials():
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)
        if creds.valid:
            return creds
        if creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError as error:
                response = error.args[1] if len(error.args) > 1 else None
                if not isinstance(response, dict) or response.get("error") != "invalid_grant":
                    raise
            else:
                TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
                return creds

    raise GmailAuthorizationRequired(
        "Token Gmail tidak tersedia atau ditolak Google. Jalankan python auth_gmail.py untuk otorisasi."
    )


def authorize():
    try:
        load_gmail_credentials()
    except GmailAuthorizationRequired as error:
        print(error)
        flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
        creds = flow.run_local_server(port=0, open_browser=True, prompt="select_account consent")
        TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")

    print("✅ Otorisasi Gmail berhasil! File token.json sudah tersimpan.")


if __name__ == "__main__":
    authorize()
