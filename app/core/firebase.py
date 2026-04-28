import os
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import auth as firebase_auth
from dotenv import load_dotenv

load_dotenv()

# Prevent double initialization if imported multiple times
if not firebase_admin._apps:
    firebase_key_path = os.getenv('FIREBASE_KEY_PATH', 'firebase_key.json')
    if os.path.exists(firebase_key_path):
        cred = credentials.Certificate(firebase_key_path)
        firebase_admin.initialize_app(cred)
    else:
        # Fallback for Google Cloud Run (uses default service account)
        firebase_admin.initialize_app()

db = firestore.client()
