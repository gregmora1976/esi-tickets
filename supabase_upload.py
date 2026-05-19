import os
import uuid
from supabase import create_client

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_BUCKET = os.getenv("SUPABASE_BUCKET", "uploads")

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

def upload_file_to_supabase(local_path, original_filename):
    ext = original_filename.split(".")[-1]
    unique_name = f"{uuid.uuid4()}.{ext}"

    with open(local_path, "rb") as f:
        supabase.storage.from_(SUPABASE_BUCKET).upload(
            unique_name,
            f,
            {"content-type": "application/octet-stream"}
        )

    public_url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(unique_name)

    return {
        "filename": unique_name,
        "url": public_url
    }
