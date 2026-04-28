import os
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

load_dotenv()

# Initialize Firebase (assuming firebase_key.json is in root)
cred_path = os.getenv('FIREBASE_CREDENTIALS', 'firebase_key.json')
if not firebase_admin._apps:
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)

db = firestore.client()

DEFAULT_TENANT_ID = "tenant_default_001"

def migrate():
    print(f"Starting Multi-Tenant Migration. Default Tenant: {DEFAULT_TENANT_ID}")
    
    # 1. Create Default Tenant
    tenant_ref = db.collection('tenants').document(DEFAULT_TENANT_ID)
    if not tenant_ref.get().exists:
        tenant_ref.set({
            'tenant_name': "Default Home",
            'status': "active",
            'created_at': datetime.now(),
            'subscription_plan': "pro",
            'max_devices': 50,
            'max_users': 10,
            'settings': {
                'timezone': "Asia/Kolkata",
                'theme': "dark"
            }
        })
        print("Created default tenant.")

    collections_to_migrate = ['users', 'admin', 'devices', 'rooms', 'boards', 'timers', 'logs']
    
    for col_name in collections_to_migrate:
        docs = db.collection(col_name).get()
        count = 0
        for doc in docs:
            data = doc.to_dict()
            if 'tenant_id' not in data:
                doc.reference.update({'tenant_id': DEFAULT_TENANT_ID})
                count += 1
        print(f"Migrated {count} documents in '{col_name}'.")

    # Super admins don't need a tenant_id as they can access all, 
    # but we might assign them to default for fallback or leave them global.
    print("Migration Complete.")

if __name__ == "__main__":
    migrate()
