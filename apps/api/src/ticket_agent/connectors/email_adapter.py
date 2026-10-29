"""Email connector over IMAP (inbound) and SMTP (outbound)."""

from __future__ import annotations

import contextlib
import email as email_lib
import html
import imaplib
import re
import smtplib
from dataclasses import dataclass
from datetime import UTC, datetime
from email.header import decode_header
from email.message import EmailMessage, Message
from email.utils import formatdate, parseaddr
from typing import Any

from ticket_agent.connectors.base import (
    ConnectorError,
    DeliveryReceipt,
    HealthCheck,
    InboundEnvelope,
    InboundFetch,
    OutboundEnvelope,
    resolve_secret,
)
from ticket_agent.connectors.models import ExternalConnector

_TAG_RE = re.compile(r"<[^>]+>")
_BREAK_RE = re.compile(r"<\s*(br|/p|/div|/li)\s*/?\s*>", re.IGNORECASE)


@dataclass(frozen=True)
class EmailConfig:
    imap_host: str
    imap_port: int
    imap_ssl: bool
    imap_folder: str
    smtp_host: str
    smtp_port: int
    smtp_ssl: bool
    smtp_starttls: bool
    username: str
    from_address: str
    timeout_seconds: float

    @classmethod
    def from_connector(cls, connector: ExternalConnector) -> EmailConfig:
        config = connector.config_json or {}
        imap_host = str(config.get("imap_host", "")).strip()
        from_address = str(config.get("from_address", "")).strip()
        username = str(config.get("username", "")).strip() or from_address
        if not imap_host:
            raise ConnectorError(
                "EMAIL_CONFIG_INVALID",
                "config.imap_host is required for email connectors.",
            )
        if not from_address:
            raise ConnectorError(
                "EMAIL_CONFIG_INVALID",
                "config.from_address is required for email connectors.",
            )
        smtp_host = str(config.get("smtp_host", "")).strip() or imap_host
        imap_ssl = bool(config.get("imap_ssl", True))
        smtp_ssl = bool(config.get("smtp_ssl", True))
        return cls(
            imap_host=imap_host,
            imap_port=_as_int(config.get("imap_port"), 993 if imap_ssl else 143),
            imap_ssl=imap_ssl,
            imap_folder=str(config.get("imap_folder", "INBOX")),
            smtp_host=smtp_host,
            smtp_port=_as_int(config.get("smtp_port"), 465 if smtp_ssl else 25),
            smtp_ssl=smtp_ssl,
            smtp_starttls=bool(config.get("smtp_starttls", False)),
            username=username,
            from_address=from_address,
            timeout_seconds=float(config.get("timeout_seconds", 20)),
        )


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    chunks: list[str] = []
    for part, charset in decode_header(value):
        if isinstance(part, bytes):
            chunks.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            chunks.append(part)
    return "".join(chunks).strip()


def _strip_html(value: str) -> str:
    text = _BREAK_RE.sub("\n", value)
    text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _part_text(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if isinstance(payload, bytes):
        charset = part.get_content_charset() or "utf-8"
        return payload.decode(charset, errors="replace")
    if isinstance(payload, str):
        return payload
    return ""


def extract_body(message: Message) -> str:
    if message.is_multipart():
        for part in message.walk():
            disposition = str(part.get("Content-Disposition") or "")
            if "attachment" in disposition.lower():
                continue
            if part.get_content_type() == "text/plain":
                text = _part_text(part).strip()
                if text:
                    return text
        for part in message.walk():
            if part.get_content_type() == "text/html":
                text = _strip_html(_part_text(part))
                if text:
                    return text
        return ""
    text = _part_text(message)
    if message.get_content_type() == "text/html":
        return _strip_html(text)
    return text.strip()


def _thread_token(value: str | None) -> str:
    for token in (value or "").split():
        token = token.strip()
        if token.startswith("<") and token.endswith(">"):
            return token
    return ""


def thread_id_for(message: Message, *, folder: str, uid: str) -> str:
    reference = _thread_token(message.get("References"))
    if reference:
        return reference
    in_reply_to = _thread_token(message.get("In-Reply-To"))
    if in_reply_to:
        return in_reply_to
    own = _thread_token(message.get("Message-ID"))
    if own:
        return own
    return f"uid:{folder}:{uid}"


def message_to_envelope(
    message: Message,
    *,
    folder: str,
    uid: str,
) -> InboundEnvelope:
    message_id = _thread_token(message.get("Message-ID")) or f"uid:{folder}:{uid}"
    sender = parseaddr(_decode_header(message.get("From")))[1]
    if not sender:
        sender = _decode_header(message.get("From"))[:256] or "unknown@unknown"
    attachment_names = [
        part.get_filename()
        for part in message.walk()
        if part.get_filename()
    ]
    return InboundEnvelope(
        external_message_id=message_id[:256],
        external_conversation_id=thread_id_for(
            message,
            folder=folder,
            uid=uid,
        )[:256],
        external_user_id=sender[:256],
        subject=_decode_header(message.get("Subject"))[:500],
        content=extract_body(message),
        raw={
            "source": "imap",
            "folder": folder,
            "uid": uid,
            "attachments": attachment_names,
            "received_at": datetime.now(UTC).isoformat(),
        },
    )


def build_outbound_message(
    *,
    from_address: str,
    message: OutboundEnvelope,
) -> EmailMessage:
    email = EmailMessage()
    email["From"] = from_address
    email["To"] = message.recipient
    email["Subject"] = message.subject or "回复"
    email["Message-ID"] = message.message_id
    email["Date"] = formatdate(localtime=False)
    if message.in_reply_to:
        email["In-Reply-To"] = message.in_reply_to
    if message.thread_id:
        email["References"] = message.thread_id
    email.set_content(message.content)
    return email


class EmailConnectorAdapter:
    """IMAP polling plus SMTP delivery for one connector row."""

    def __init__(self, connector: ExternalConnector) -> None:
        self.connector = connector
        self.config = EmailConfig.from_connector(connector)
        self._password: str | None = None

    def _credentials(self) -> str:
        if self._password is not None:
            return self._password
        if self.connector.secret_ref:
            self._password = resolve_secret(self.connector.secret_ref)
        else:
            self._password = ""
        return self._password

    def _imap(self) -> Any:
        if self.config.imap_ssl:
            client: Any = imaplib.IMAP4_SSL(
                self.config.imap_host,
                self.config.imap_port,
                timeout=self.config.timeout_seconds,
            )
        else:
            client = imaplib.IMAP4(
                self.config.imap_host,
                self.config.imap_port,
                timeout=self.config.timeout_seconds,
            )
        password = self._credentials()
        if password and self.config.username:
            client.login(self.config.username, password)
        return client

    def health(self) -> HealthCheck:
        try:
            client = self._imap()
            try:
                status, data = client.select(self.config.imap_folder, readonly=True)
                if status != "OK":
                    raise ConnectorError(
                        "EMAIL_IMAP_FOLDER",
                        f"IMAP folder {self.config.imap_folder} is unavailable.",
                    )
            finally:
                client.logout()
            self._smtp_probe()
        except ConnectorError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as health detail
            raise ConnectorError(
                "EMAIL_HEALTH_FAILED",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        return HealthCheck(
            healthy=True,
            detail="IMAP folder and SMTP endpoint reachable.",
            metadata={
                "imap_host": self.config.imap_host,
                "imap_folder": self.config.imap_folder,
                "smtp_host": self.config.smtp_host,
            },
        )

    def _smtp_probe(self) -> None:
        client = self._smtp()
        try:
            client.noop()
        finally:
            client.quit()

    def _smtp(self) -> Any:
        if self.config.smtp_ssl:
            client: Any = smtplib.SMTP_SSL(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=self.config.timeout_seconds,
            )
        else:
            client = smtplib.SMTP(
                self.config.smtp_host,
                self.config.smtp_port,
                timeout=self.config.timeout_seconds,
            )
            if self.config.smtp_starttls:
                client.starttls()
        password = self._credentials()
        if password and self.config.username:
            client.login(self.config.username, password)
        return client

    def fetch_inbound(self, *, limit: int) -> list[InboundFetch]:
        try:
            client = self._imap()
        except Exception as exc:  # noqa: BLE001
            raise ConnectorError(
                "EMAIL_IMAP_CONNECT_FAILED",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        fetched: list[InboundFetch] = []
        try:
            status, _ = client.select(self.config.imap_folder, readonly=False)
            if status != "OK":
                raise ConnectorError(
                    "EMAIL_IMAP_FOLDER",
                    f"IMAP folder {self.config.imap_folder} is unavailable.",
                    retryable=True,
                )
            status, data = client.uid("search", None, "UNSEEN")
            if status != "OK":
                raise ConnectorError(
                    "EMAIL_IMAP_SEARCH_FAILED",
                    "IMAP UNSEEN search failed.",
                    retryable=True,
                )
            raw_ids = b" ".join(
                item for item in data if isinstance(item, bytes)
            ).split()
            for uid_bytes in raw_ids[: max(limit, 1)]:
                uid = uid_bytes.decode("ascii", errors="replace")
                status, payload = client.uid("fetch", uid, "(RFC822)")
                if status != "OK" or not payload:
                    continue
                raw = next(
                    (
                        item[1]
                        for item in payload
                        if isinstance(item, tuple)
                        and len(item) > 1
                        and isinstance(item[1], bytes)
                    ),
                    None,
                )
                if raw is None:
                    continue
                message = email_lib.message_from_bytes(raw)
                fetched.append(
                    InboundFetch(
                        envelope=message_to_envelope(
                            message,
                            folder=self.config.imap_folder,
                            uid=uid,
                        ),
                        ack_token=f"{self.config.imap_folder}|{uid}",
                    )
                )
        finally:
            # Logout errors are not actionable once messages were parsed.
            with contextlib.suppress(Exception):
                client.logout()
        return fetched

    def acknowledge(self, token: str) -> None:
        folder, _, uid = token.partition("|")
        if not uid:
            return
        client = self._imap()
        try:
            client.select(folder or self.config.imap_folder, readonly=False)
            client.uid("store", uid, "+FLAGS", "(\\Seen)")
        finally:
            with contextlib.suppress(Exception):
                client.logout()

    def send(self, message: OutboundEnvelope) -> DeliveryReceipt:
        email = build_outbound_message(
            from_address=self.config.from_address,
            message=message,
        )
        try:
            client = self._smtp()
            try:
                client.send_message(email)
            finally:
                client.quit()
        except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused):
            raise ConnectorError(
                "EMAIL_RECIPIENT_REJECTED",
                "SMTP server rejected the recipient.",
            ) from None
        except smtplib.SMTPAuthenticationError:
            raise ConnectorError(
                "EMAIL_AUTH_FAILED",
                "SMTP authentication failed.",
            ) from None
        except (smtplib.SMTPException, OSError) as exc:
            raise ConnectorError(
                "EMAIL_SMTP_FAILED",
                f"{type(exc).__name__}: {exc}",
                retryable=True,
            ) from exc
        return DeliveryReceipt(
            external_message_id=message.message_id,
            detail={"smtp_host": self.config.smtp_host},
        )
