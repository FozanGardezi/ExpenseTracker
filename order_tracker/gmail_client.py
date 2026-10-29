"""Thin wrapper over the Gmail API calls the tracker makes."""

import base64
import datetime as dt

from googleapiclient.discovery import build

from .email_utils import extract_bodies, pdf_parts
from .models import Attachment, Email


class GmailClient:
    def __init__(self, credentials):
        self.service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def account_email(self) -> str:
        return self.service.users().getProfile(userId="me").execute()["emailAddress"]

    def list_message_ids(self, query: str) -> list[str]:
        """All message ids matching a Gmail search query, following pagination."""
        ids: list[str] = []
        page_token = None
        while True:
            response = self.service.users().messages().list(
                userId="me", q=query, maxResults=500, pageToken=page_token
            ).execute(num_retries=3)
            ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return ids

    def get_email(self, message_id: str, attachments: bool = False) -> Email:
        """One message; with `attachments`, its PDF attachments are downloaded too."""
        message = self.service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute(num_retries=3)
        payload = message.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        return Email(
            message_id=message_id,
            sender=headers.get("from", ""),
            subject=headers.get("subject", ""),
            received_at=dt.datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=dt.UTC),
            bodies=extract_bodies(payload),
            attachments=[self._attachment(message_id, part) for part in pdf_parts(payload)] if attachments else [],
        )

    def _attachment(self, message_id: str, part: dict) -> Attachment:
        body = part.get("body") or {}
        data = body.get("data")
        if not data:
            data = self.service.users().messages().attachments().get(
                userId="me", messageId=message_id, id=body["attachmentId"]
            ).execute(num_retries=3)["data"]
        return Attachment(
            filename=part.get("filename") or "statement.pdf",
            mime_type=part.get("mimeType", ""),
            data=base64.urlsafe_b64decode(data),
        )
