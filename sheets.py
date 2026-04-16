import os
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SHEET_ID = os.getenv('GOOGLE_SHEET_ID')

def get_service():
    creds = service_account.Credentials.from_service_account_file(
        'credentials.json', scopes=SCOPES
    )
    return build('sheets', 'v4', credentials=creds)

def append_row(fecha, monto, concepto, categoria):
    service = get_service()
    service.spreadsheets().values().append(
        spreadsheetId=SHEET_ID,
        range='Hoja1!A:D',
        valueInputOption='RAW',
        body={'values': [[fecha, monto, concepto, categoria]]}
    ).execute()

def get_all_rows():
    service = get_service()
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID,
        range='Hoja1!A:D'
    ).execute()
    rows = result.get('values', [])
    if len(rows) < 2:
        return []
    headers = [h.lower() for h in rows[0]]
    return [dict(zip(headers, row)) for row in rows[1:]]