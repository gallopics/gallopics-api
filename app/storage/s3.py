import io
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from fastapi import UploadFile

from app.storage.base import StorageBackend


class S3StorageBackend(StorageBackend):
    def __init__(self, settings):
        self.bucket = settings.storage_s3_bucket
        self.region = settings.storage_s3_region
        self.endpoint_url = settings.storage_s3_endpoint_url or None
        self.access_key = settings.storage_s3_access_key or None
        self.secret_key = settings.storage_s3_secret_key or None
        self._s3 = None

    def _get_s3(self):
        if self._s3 is None:
            kwargs = {"region_name": self.region}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.access_key and self.secret_key:
                kwargs["aws_access_key_id"] = self.access_key
                kwargs["aws_secret_access_key"] = self.secret_key
            self._s3 = boto3.client("s3", **kwargs)
        return self._s3

    async def generate_presigned_upload_url(
        self, key: str, content_type: str, expires_in: int = 3600
    ) -> str:
        s3 = self._get_s3()
        extra_params = {"ContentType": content_type}
        url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                **extra_params,
            },
            ExpiresIn=expires_in,
        )
        return url

    async def generate_presigned_download_url(
        self, key: str, expires_in: int = 3600
    ) -> str:
        s3 = self._get_s3()
        url = s3.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
            },
            ExpiresIn=expires_in,
        )
        return url

    async def download_to_path(self, key: str, local_path: str) -> None:
        s3 = self._get_s3()
        s3.download_file(self.bucket, key, local_path)

    async def upload_from_path(
        self, local_path: str, key: str, content_type: str
    ) -> None:
        s3 = self._get_s3()
        s3.upload_file(
            local_path,
            self.bucket,
            key,
            ExtraArgs={"ContentType": content_type},
        )

    async def delete_object(self, key: str) -> None:
        s3 = self._get_s3()
        s3.delete_object(Bucket=self.bucket, Key=key)

    async def object_exists(self, key: str) -> bool:
        s3 = self._get_s3()
        try:
            s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    async def write_upload_file(self, file: UploadFile, key: str) -> str:
        """Upload an UploadFile directly to S3."""
        s3 = self._get_s3()
        content_type = file.content_type or "application/octet-stream"
        s3.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=await file.read(),
            ContentType=content_type,
        )
        return key
