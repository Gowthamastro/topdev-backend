"""S3 file storage service — resume and JD uploads with signed URL generation."""
import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
import uuid
import mimetypes


def get_s3_client():
    return boto3.client(
        "s3",
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION,
    )


def generate_s3_key(folder: str, filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
    return f"{folder}/{uuid.uuid4()}.{ext}"


async def upload_file(file_bytes: bytes, filename: str, folder: str = "uploads") -> str | None:
    """Upload file to S3, return the S3 key."""
    if not settings.AWS_ACCESS_KEY_ID:
        print(f"[MOCK S3] Uploading {filename} to virtual {folder}/")
        ext = filename.rsplit(".", 1)[-1] if "." in filename else "bin"
        return f"mock_{folder}/{uuid.uuid4()}.{ext}"

    try:
        s3 = get_s3_client()
        key = generate_s3_key(folder, filename)
        content_type, _ = mimetypes.guess_type(filename)
        s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=key,
            Body=file_bytes,
            ContentType=content_type or "application/octet-stream",
        )
        return key
    except ClientError as e:
        print(f"[S3 UPLOAD ERROR] {e}")
        return None


def get_signed_url(s3_key: str, expiry: int = None) -> str | None:
    """Generate a pre-signed URL for secure file access."""
    if not settings.AWS_ACCESS_KEY_ID:
        return f"https://mock-s3.local/{s3_key}"

    try:
        s3 = get_s3_client()
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=expiry or settings.S3_SIGNED_URL_EXPIRY,
        )
        return url
    except ClientError as e:
        print(f"[S3 SIGNED URL ERROR] {e}")
        return None


async def delete_file(s3_key: str) -> bool:
    if not settings.AWS_ACCESS_KEY_ID:
        return True

    try:
        s3 = get_s3_client()
        s3.delete_object(Bucket=settings.S3_BUCKET_NAME, Key=s3_key)
        return True
    except ClientError:
        return False
