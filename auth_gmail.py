# auth_gmail.py — jalankan sekali untuk otorisasi Gmail
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
import os

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

def authorize():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES
            )
            creds = flow.run_local_server(port=8080, open_browser=True)
        
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    print("✅ Otorisasi Gmail berhasil! File token.json sudah tersimpan.")

if __name__ == "__main__":
    authorize()