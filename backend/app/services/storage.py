"""
S3-compatible file storage service.
Works with: AWS S3, MinIO, Alibaba OSS, Tencent COS (all boto3-compatible).
"""
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
import structlog

from app.core.config import settings

logger = structlog.get_logger(__name__)


class StorageService:
    def __init__(self):
        common_kwargs = {
            "aws_access_key_id": settings.S3_ACCESS_KEY_ID,
            "aws_secret_access_key": settings.S3_SECRET_ACCESS_KEY,
            "region_name": settings.S3_REGION_NAME,
            "config": Config(signature_version="s3v4"),
        }

        # Internal client: used for server-side operations (upload results, download, list)
        internal_kwargs = {**common_kwargs}
        if settings.S3_ENDPOINT_URL:
            internal_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        self.client = boto3.client("s3", **internal_kwargs)

        # External client: used for generating presigned URLs accessible from the browser.
        # Must use the external URL so the signature is computed with the correct host header.
        external_kwargs = {**common_kwargs}
        if settings.S3_EXTERNAL_URL:
            external_kwargs["endpoint_url"] = settings.S3_EXTERNAL_URL
        elif settings.S3_ENDPOINT_URL:
            external_kwargs["endpoint_url"] = settings.S3_ENDPOINT_URL
        self.external_client = boto3.client("s3", **external_kwargs)

        self.bucket = settings.S3_BUCKET_NAME

    def generate_upload_presigned_url(self, key: str, content_type: str, expires: int = None) -> str:
        """Generate a presigned URL for direct browser upload."""
        try:
            return self.external_client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ContentType": content_type,
                },
                ExpiresIn=expires or settings.S3_PRESIGN_EXPIRE_SECONDS,
            )
        except ClientError as e:
            logger.error("Failed to generate upload presigned URL", key=key, error=str(e))
            raise

    def generate_download_presigned_url(self, key: str, expires: int = None, filename: str = None) -> str:
        """Generate a presigned URL for file download."""
        params = {"Bucket": self.bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        try:
            return self.external_client.generate_presigned_url(
                "get_object",
                Params=params,
                ExpiresIn=expires or settings.S3_PRESIGN_EXPIRE_SECONDS,
            )
        except ClientError as e:
            logger.error("Failed to generate download presigned URL", key=key, error=str(e))
            raise

    def upload_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
        """Upload bytes directly (used by worker to save results)."""
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def download_bytes(self, key: str) -> bytes:
        """Download an object as bytes."""
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete_object(self, key: str) -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            logger.warning("Failed to delete object", key=key, error=str(e))

    def list_objects(self, prefix: str) -> list[dict]:
        """List objects under a prefix, returns [{key, size, last_modified}]."""
        try:
            response = self.client.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            return [
                {
                    "key": obj["Key"],
                    "size": obj["Size"],
                    "last_modified": obj["LastModified"].isoformat(),
                }
                for obj in response.get("Contents", [])
            ]
        except ClientError as e:
            logger.error("Failed to list objects", prefix=prefix, error=str(e))
            return []

    def ensure_bucket_exists(self) -> None:
        """Create bucket if it doesn't exist (useful for MinIO setups)."""
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except ClientError:
            kwargs = {"Bucket": self.bucket}
            if settings.S3_REGION_NAME != "us-east-1":
                kwargs["CreateBucketConfiguration"] = {"LocationConstraint": settings.S3_REGION_NAME}
            self.client.create_bucket(**kwargs)
            logger.info("Created S3 bucket", bucket=self.bucket)


storage_service = StorageService()
