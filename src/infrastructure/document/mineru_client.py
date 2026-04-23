from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import requests

from config.settings import settings


class MineruApiError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MineruUploadBatch:
    batch_id: str
    file_urls: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MineruExtractResult:
    file_name: str | None
    state: str
    data_id: str | None = None
    full_zip_url: str | None = None
    err_msg: str | None = None
    extract_progress: dict[str, Any] | None = None


class MineruClient:
    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        request_timeout: float | None = None,
        upload_timeout: float | None = None,
        download_timeout: float | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.token = (token if token is not None else settings.MINERU_API_TOKEN).strip()
        self.base_url = (base_url or settings.MINERU_BASE_URL).rstrip("/")
        self.request_timeout = float(request_timeout or settings.MINERU_REQUEST_TIMEOUT_SECONDS)
        self.upload_timeout = float(upload_timeout or settings.MINERU_UPLOAD_TIMEOUT_SECONDS)
        self.download_timeout = float(download_timeout or settings.MINERU_DOWNLOAD_TIMEOUT_SECONDS)
        self.session = session or requests.Session()

    def create_upload_batch(
        self,
        *,
        file_name: str,
        data_id: str,
        model_version: str,
        language: str,
        enable_formula: bool,
        enable_table: bool,
        is_ocr: bool,
    ) -> MineruUploadBatch:
        payload = {
            "files": [
                {
                    "name": file_name,
                    "data_id": data_id,
                    "is_ocr": is_ocr,
                }
            ],
            "model_version": model_version,
            "language": language,
            "enable_formula": enable_formula,
            "enable_table": enable_table,
        }
        data = self._request_json("POST", "/api/v4/file-urls/batch", json_payload=payload)
        batch_id = str(data.get("batch_id") or "").strip()
        file_urls = tuple(str(url) for url in data.get("file_urls") or [] if str(url).strip())
        if not batch_id or not file_urls:
            raise MineruApiError("MinerU did not return a batch_id and upload URL")
        return MineruUploadBatch(batch_id=batch_id, file_urls=file_urls)

    def upload_file(self, upload_url: str, file_path: Path) -> None:
        with Path(file_path).open("rb") as handle:
            response = self.session.put(upload_url, data=handle, timeout=self.upload_timeout)
        if response.status_code not in {200, 201, 204}:
            raise MineruApiError(f"MinerU file upload failed: HTTP {response.status_code}")

    def get_batch_results(self, batch_id: str) -> list[MineruExtractResult]:
        data = self._request_json("GET", f"/api/v4/extract-results/batch/{batch_id}")
        results = data.get("extract_result") or []
        if not isinstance(results, list):
            raise MineruApiError("MinerU returned an invalid extract_result payload")
        return [
            MineruExtractResult(
                file_name=_optional_str(item.get("file_name")),
                state=str(item.get("state") or "").strip(),
                data_id=_optional_str(item.get("data_id")),
                full_zip_url=_optional_str(item.get("full_zip_url")),
                err_msg=_optional_str(item.get("err_msg")),
                extract_progress=item.get("extract_progress") if isinstance(item.get("extract_progress"), dict) else None,
            )
            for item in results
            if isinstance(item, Mapping)
        ]

    def download_result_zip(self, full_zip_url: str, target_path: Path) -> None:
        response = self.session.get(full_zip_url, stream=True, timeout=self.download_timeout)
        if response.status_code != 200:
            raise MineruApiError(f"MinerU result download failed: HTTP {response.status_code}")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with target_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)

    def _request_json(self, method: str, path: str, *, json_payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise MineruApiError("MINERU_API_TOKEN is required")

        url = f"{self.base_url}{path}"
        headers = {
            "Accept": "*/*",
            "Authorization": f"Bearer {self.token}",
        }
        if json_payload is not None:
            headers["Content-Type"] = "application/json"

        response = self.session.request(
            method,
            url,
            json=json_payload,
            headers=headers,
            timeout=self.request_timeout,
        )
        try:
            body = response.json()
        except ValueError as exc:
            raise MineruApiError(f"MinerU returned non-JSON response: HTTP {response.status_code}") from exc

        if response.status_code != 200:
            message = body.get("msg") if isinstance(body, dict) else None
            raise MineruApiError(message or f"MinerU request failed: HTTP {response.status_code}")
        if not isinstance(body, dict):
            raise MineruApiError("MinerU returned an invalid response body")
        if body.get("code") != 0:
            code = body.get("code")
            message = body.get("msg") or "MinerU request failed"
            raise MineruApiError(f"{message} ({code})")
        data = body.get("data")
        if not isinstance(data, dict):
            raise MineruApiError("MinerU returned an invalid data payload")
        return data


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
