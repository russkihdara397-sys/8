"""
Omni Messenger — десктопное приложение.
Запуск:
    pip install fastapi uvicorn[standard] sqlalchemy aiosqlite pydantic pywebview
    python main.py            # нативное окно
    python main.py --web      # в браузере
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import random
import socket
import sys
import threading
import time
import uuid
import webbrowser
from abc import ABC, abstractmethod
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("omni")


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================
def _user_data_dir() -> Path:
    home = Path.home()
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or home / "AppData" / "Roaming")
        folder = base / "OmniMessenger"
    elif sys.platform == "darwin":
        folder = home / "Library" / "Application Support" / "OmniMessenger"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
        folder = base / "omni-messenger"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


APP_DATA_DIR = _user_data_dir()
DB_PATH = APP_DATA_DIR / "omni.db"
DB_URL = os.getenv("DB_URL", f"sqlite+aiosqlite:///{DB_PATH.as_posix()}")
MOCK_FAILURE_RATE = float(os.getenv("MOCK_FAILURE_RATE", "0.2"))
DELIVERY_PROBABILITY = 0.75
SMALL_SAMPLE_THRESHOLD = 10


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


engine = create_async_engine(
    DB_URL, echo=False, future=True,
    connect_args={"timeout": 30} if DB_URL.startswith("sqlite") else {},
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


# ============================================================
# МОДЕЛИ
# ============================================================
class Contact(Base):
    __tablename__ = "contacts"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram_id: Mapped[str | None] = mapped_column(String(64))
    push_token: Mapped[str | None] = mapped_column(String(255))
    default_channel: Mapped[str] = mapped_column(String(16), default="email")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    def address_for(self, channel: str) -> str | None:
        return {"email": self.email, "sms": self.phone,
                "push": self.push_token, "telegram": self.telegram_id}.get(channel)


class Cascade(Base):
    __tablename__ = "cascades"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    steps: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Campaign(Base):
    __tablename__ = "campaigns"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    channels: Mapped[list] = mapped_column(JSON, default=list)
    cascade_id: Mapped[int | None] = mapped_column(ForeignKey("cascades.id"))
    status: Mapped[str] = mapped_column(String(16), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Message(Base):
    __tablename__ = "messages"
    id: Mapped[int] = mapped_column(primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    campaign_id: Mapped[int | None] = mapped_column(ForeignKey("campaigns.id"))
    cascade_id: Mapped[int | None] = mapped_column(ForeignKey("cascades.id"))
    channel: Mapped[str] = mapped_column(String(16), index=True)
    subject: Mapped[str] = mapped_column(String(255), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    step_index: Mapped[int] = mapped_column(default=0)
    provider_id: Mapped[str | None] = mapped_column(String(128))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    contact: Mapped["Contact"] = relationship(lazy="selectin")


class Integration(Base):
    __tablename__ = "integrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(64))
    channel: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24), default="setup_required")
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class IntegrationErrorLog(Base):
    __tablename__ = "integration_errors"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(32), index=True)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ============================================================
# СХЕМЫ
# ============================================================
class ContactIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    email: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    telegram_id: str | None = Field(default=None, max_length=64)
    push_token: str | None = Field(default=None, max_length=255)
    default_channel: str = "email"


class ContactOut(ContactIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class BulkDeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1)


class PreviewIn(BaseModel):
    body: str = ""
    subject: str = ""
    channels: list[str] = Field(default_factory=lambda: ["email", "sms", "push", "telegram"])


class SendRequest(BaseModel):
    contact_ids: list[int]
    channels: list[str] = Field(default_factory=lambda: ["email"])
    subject: str = Field(default="", max_length=255)
    body: str = Field(default="", max_length=4096)
    cascade_id: int | None = None


class CascadeStep(BaseModel):
    channel: str
    delay_seconds: int = Field(ge=1, le=300)


class CascadeIn(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    steps: list[CascadeStep] = Field(min_length=1)


class CascadeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    steps: list[dict]


class IntegrationIn(BaseModel):
    config: dict = Field(default_factory=dict)


class IntegrationErrorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    message: str
    created_at: datetime


class IntegrationOut(BaseModel):
    provider: str
    title: str
    channel: str
    status: str
    reason: str
    configured_keys: list[str]
    errors: list[IntegrationErrorOut]


# ============================================================
# АДАПТЕРЫ
# ============================================================
@dataclass(slots=True)
class SendResult:
    ok: bool
    provider_id: str | None = None
    error: str | None = None


class ChannelAdapter(ABC):
    channel: str = ""
    title: str = ""
    emoji: str = ""
    color: str = ""

    async def _mock_send(self) -> SendResult:
        await asyncio.sleep(random.uniform(0.1, 0.4))
        if random.random() < MOCK_FAILURE_RATE:
            return SendResult(False, error="Провайдер временно недоступен")
        return SendResult(True, provider_id=f"mock-{uuid.uuid4().hex[:12]}")

    @abstractmethod
    async def send(self, contact: "Contact", subject: str, body: str) -> SendResult: ...


class EmailAdapter(ChannelAdapter):
    channel, title, emoji, color = "email", "Email", "📧", "#3B82F6"

    async def send(self, contact, subject, body):
        if not contact.address_for("email"):
            return SendResult(False, error="У контакта нет email")
        return await self._mock_send()


class SmsAdapter(ChannelAdapter):
    channel, title, emoji, color = "sms", "SMS", "💬", "#22C55E"

    async def send(self, contact, subject, body):
        if not contact.address_for("sms"):
            return SendResult(False, error="У контакта нет телефона")
        return await self._mock_send()


class PushAdapter(ChannelAdapter):
    channel, title, emoji, color = "push", "Push", "📱", "#F59E0B"

    async def send(self, contact, subject, body):
        if not contact.address_for("push"):
            return SendResult(False, error="Нет push-токена")
        return await self._mock_send()


class TelegramAdapter(ChannelAdapter):
    channel, title, emoji, color = "telegram", "Telegram", "✈️", "#38BDF8"

    async def send(self, contact, subject, body):
        if not contact.address_for("telegram"):
            return SendResult(False, error="Нет Telegram ID")
        return await self._mock_send()


_ADAPTERS: dict[str, ChannelAdapter] = {
    a.channel: a for a in (EmailAdapter(), SmsAdapter(), PushAdapter(), TelegramAdapter())
}


def get_adapter(channel: str) -> ChannelAdapter:
    if channel not in _ADAPTERS:
        raise KeyError(f"Неизвестный канал: {channel}")
    return _ADAPTERS[channel]


def channel_meta() -> list[dict]:
    return [{"key": a.channel, "title": a.title, "emoji": a.emoji, "color": a.color}
            for a in _ADAPTERS.values()]


# ============================================================
# КОМПОЗЕР
# ============================================================
_GSM_BASIC = set(
    "@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà"
)
_GSM_EXT = set("^{}\\[~]|€")
MAX_SMS_PARTS = 3


def sms_info(text: str) -> dict:
    gsm = all(ch in _GSM_BASIC or ch in _GSM_EXT for ch in text)
    weight = sum(2 if ch in _GSM_EXT else 1 for ch in text) if gsm else len(text)
    single, multi = (160, 153) if gsm else (70, 67)
    parts = 1 if weight <= single else math.ceil(weight / multi)
    limit = single if parts == 1 else multi
    remaining = limit - (weight if parts == 1 else weight - multi * (parts - 1))
    return {"chars": len(text), "weight": weight,
            "encoding": "GSM-7" if gsm else "UCS-2",
            "parts": parts, "limit": limit, "remaining": remaining}


def adapt_for_channel(body: str, channel: str) -> str:
    if channel == "sms":
        if sms_info(body)["parts"] > MAX_SMS_PARTS:
            return body[:153 * (MAX_SMS_PARTS - 1) - 1] + "…"
        return body
    if channel == "push":
        return body if len(body) <= 240 else body[:239] + "…"
    if channel == "telegram":
        return body if len(body) <= 4096 else body[:4095] + "…"
    return body


def preview_channels(body: str, subject: str, channels: list[str]) -> list[dict]:
    result = []
    for ch in channels:
        if ch == "sms":
            result.append({"channel": "sms", "text": adapt_for_channel(body, "sms"),
                           "meta": sms_info(body)})
        elif ch == "email":
            result.append({"channel": "email", "subject": subject, "html": body, "meta": {}})
        elif ch == "push":
            result.append({"channel": "push", "title": subject or "Уведомление",
                           "text": adapt_for_channel(body, "push"), "meta": {}})
        elif ch == "telegram":
            result.append({"channel": "telegram",
                           "text": adapt_for_channel(body, "telegram"), "meta": {}})
    return result


# ============================================================
# WEBSOCKET
# ============================================================
class ConnectionManager:
    def __init__(self) -> None:
        self.active: set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self.active.discard(ws)

    async def broadcast(self, payload: dict) -> None:
        dead: list[WebSocket] = []
        for ws in list(self.active):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


# ============================================================
# ОТПРАВКА
# ============================================================
_background_tasks: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


def serialize_message(m: Message, contact_name: str | None = None) -> dict:
    return {
        "id": m.id, "contact_id": m.contact_id,
        "contact": contact_name or (m.contact.name if m.contact else None),
        "channel": m.channel, "subject": m.subject, "body": m.body,
        "status": m.status, "step_index": m.step_index, "error": m.error,
        "created_at": m.created_at.isoformat() if m.created_at else None,
        "updated_at": m.updated_at.isoformat() if m.updated_at else None,
        "delivered_at": m.delivered_at.isoformat() if m.delivered_at else None,
        "retryable": m.status == "failed",
    }


async def _emit(msg: Message, contact_name: str) -> None:
    await ws_manager.broadcast({"type": "message",
                                "message": serialize_message(msg, contact_name)})


async def deliver_one(
    contact_id: int, steps: list[dict], subject: str, body: str,
    campaign_id: int | None = None, cascade_id: int | None = None,
) -> None:
    async with SessionLocal() as db:
        contact = await db.get(Contact, contact_id)
        if contact is None:
            return

        for idx, step in enumerate(steps):
            channel = step["channel"]
            if not contact.address_for(channel):
                continue

            msg = Message(
                contact_id=contact.id, campaign_id=campaign_id, cascade_id=cascade_id,
                channel=channel, subject=subject,
                body=adapt_for_channel(body, channel),
                status="queued", step_index=idx,
            )
            db.add(msg)
            await db.commit()
            await _emit(msg, contact.name)

            adapter = get_adapter(channel)
            result = await adapter.send(contact, subject, body)

            if result.ok:
                msg.status = "sent"
                msg.provider_id = result.provider_id
            else:
                msg.status = "failed"
                msg.error = result.error
            msg.updated_at = utcnow()
            await db.commit()
            await _emit(msg, contact.name)

            if not result.ok:
                continue

            delay = int(step.get("delay_seconds", 0))
            if delay:
                await asyncio.sleep(delay)

            if random.random() < DELIVERY_PROBABILITY:
                msg.status = "delivered"
                msg.delivered_at = utcnow()
                msg.updated_at = utcnow()
                await db.commit()
                await _emit(msg, contact.name)
                return

            msg.status = "failed"
            msg.error = "Истёк срок доставки (таймаут ожидания подтверждения)"
            msg.updated_at = utcnow()
            await db.commit()
            await _emit(msg, contact.name)


def start_delivery(
    contact_ids: list[int], steps: list[dict], subject: str, body: str,
    campaign_id: int | None = None, cascade_id: int | None = None,
) -> None:
    for cid in contact_ids:
        spawn(deliver_one(cid, steps, subject, body, campaign_id, cascade_id))


# ============================================================
# АНАЛИТИКА
# ============================================================
async def analytics_summary(db: AsyncSession) -> dict:
    now = utcnow()
    day_ago = now - timedelta(hours=24)
    prev_day_ago = now - timedelta(hours=48)

    cur_rows = (await db.scalars(
        select(Message).where(Message.created_at >= day_ago).order_by(Message.id.desc())
    )).all()
    prev_rows = (await db.scalars(
        select(Message).where(Message.created_at >= prev_day_ago,
                              Message.created_at < day_ago)
    )).all()

    def calc(rows):
        by_status = Counter(m.status for m in rows)
        by_channel = Counter(m.channel for m in rows)
        total = len(rows)
        delivered = by_status.get("delivered", 0) + by_status.get("read", 0)
        failed = by_status.get("failed", 0)
        return {
            "total": total, "by_status": dict(by_status),
            "by_channel": dict(by_channel),
            "delivered_count": delivered, "failed_count": failed,
            "delivery_rate": round(delivered / total * 100, 1) if total else 0.0,
            "failure_rate": round(failed / total * 100, 1) if total else 0.0,
        }

    cur = calc(cur_rows)
    prev = calc(prev_rows)

    buckets = [0] * 24
    for m in cur_rows:
        if m.status in ("delivered", "read"):
            hours_ago = int((now - m.created_at).total_seconds() // 3600)
            if 0 <= hours_ago < 24:
                buckets[23 - hours_ago] += 1

    small = cur["total"] < SMALL_SAMPLE_THRESHOLD
    return {
        **cur,
        "is_small_sample": small,
        "period_text": "скользящие 24 часа с текущего момента",
        "prev": prev,
        "delivery_delta": round(cur["delivery_rate"] - prev["delivery_rate"], 1),
        "failure_delta": round(cur["failure_rate"] - prev["failure_rate"], 1),
        "hourly_delivered": buckets,
        "has_chart_data": any(buckets),
    }


# ============================================================
# REST API
# ============================================================
router = APIRouter()


@router.get("/channels")
async def list_channels():
    return channel_meta()


# ---------- Контакты ----------
@router.get("/contacts", response_model=list[ContactOut])
async def list_contacts(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Contact).order_by(Contact.id))).all()


@router.post("/contacts", response_model=ContactOut, status_code=201)
async def create_contact(payload: ContactIn, db: AsyncSession = Depends(get_db)):
    contact = Contact(**payload.model_dump())
    db.add(contact)
    await db.commit()
    return contact


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, db: AsyncSession = Depends(get_db)):
    contact = await db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Контакт не найден")
    await db.execute(delete(Message).where(Message.contact_id == contact_id))
    await db.delete(contact)
    await db.commit()


@router.post("/contacts/bulk-delete")
async def bulk_delete_contacts(payload: BulkDeleteIn, db: AsyncSession = Depends(get_db)):
    if not payload.ids:
        return {"deleted": 0}
    await db.execute(delete(Message).where(Message.contact_id.in_(payload.ids)))
    await db.execute(delete(Contact).where(Contact.id.in_(payload.ids)))
    await db.commit()
    return {"deleted": len(payload.ids)}


@router.get("/contacts/{contact_id}/messages")
async def contact_messages(contact_id: int, limit: int = 100,
                           db: AsyncSession = Depends(get_db)):
    contact = await db.get(Contact, contact_id)
    if not contact:
        raise HTTPException(404, "Контакт не найден")
    rows = (await db.scalars(
        select(Message).where(Message.contact_id == contact_id)
        .order_by(Message.id.desc()).limit(limit)
    )).all()
    return [serialize_message(m, contact.name) for m in rows]


# ---------- Композер ----------
@router.post("/composer/preview")
async def composer_preview(payload: PreviewIn):
    return preview_channels(payload.body, payload.subject, payload.channels)


@router.post("/messages/send")
async def send_messages(payload: SendRequest, db: AsyncSession = Depends(get_db)):
    if not payload.contact_ids:
        raise HTTPException(400, "Выберите хотя бы одного получателя")
    if not payload.body.strip():
        raise HTTPException(400, "Введите текст сообщения")

    contacts = (await db.scalars(
        select(Contact).where(Contact.id.in_(payload.contact_ids))
    )).all()
    if not contacts:
        raise HTTPException(400, "Контакты не найдены")

    if payload.cascade_id:
        cascade = await db.get(Cascade, payload.cascade_id)
        if not cascade:
            raise HTTPException(404, "Каскад не найден")
        steps = cascade.steps
        channels = [s["channel"] for s in steps]
    else:
        if not payload.channels:
            raise HTTPException(400, "Укажите хотя бы один канал для отправки")
        for ch in payload.channels:
            try:
                get_adapter(ch)
            except KeyError as exc:
                raise HTTPException(400, str(exc))
        steps = [{"channel": ch, "delay_seconds": 0} for ch in payload.channels]
        channels = payload.channels

    campaign = Campaign(
        name=payload.subject or "Без темы",
        subject=payload.subject, body=payload.body,
        channels=channels, cascade_id=payload.cascade_id, status="running",
    )
    db.add(campaign)
    await db.commit()

    start_delivery(
        contact_ids=[c.id for c in contacts], steps=steps,
        subject=payload.subject, body=payload.body,
        campaign_id=campaign.id, cascade_id=payload.cascade_id,
    )
    return {"campaign_id": campaign.id, "queued": len(contacts), "steps": len(steps)}


@router.get("/messages")
async def list_messages(limit: int = 50, db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(
        select(Message).order_by(Message.id.desc()).limit(limit)
    )).all()
    return [serialize_message(m) for m in rows]


@router.get("/messages/{message_id}")
async def get_message(message_id: int, db: AsyncSession = Depends(get_db)):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(404, "Сообщение не найдено")
    return serialize_message(msg)


@router.post("/messages/{message_id}/retry")
async def retry_message(message_id: int, db: AsyncSession = Depends(get_db)):
    msg = await db.get(Message, message_id)
    if not msg:
        raise HTTPException(404, "Сообщение не найдено")
    start_delivery(
        contact_ids=[msg.contact_id],
        steps=[{"channel": msg.channel, "delay_seconds": 0}],
        subject=msg.subject, body=msg.body,
        campaign_id=msg.campaign_id, cascade_id=None,
    )
    return {"ok": True, "queued": 1}


@router.get("/analytics/summary")
async def analytics_endpoint(db: AsyncSession = Depends(get_db)):
    return await analytics_summary(db)


# ---------- Интеграции ----------
_STATUS_REASON = {
    "setup_required": "Не подключено — ключи не заданы. Нажмите «Подключить».",
    "connected": "Подключено и работает. Отключение деактивирует канал, но не удалит ключи.",
    "auth_error": "Ошибка аутентификации — проверьте API-ключи и права доступа.",
    "needs_refresh": "Ключи устарели — требуется обновление.",
    "rate_limited": "Превышен лимит запросов к провайдеру — попробуйте позже.",
}


async def _integration_out(db: AsyncSession, i: Integration) -> IntegrationOut:
    errors = (await db.scalars(
        select(IntegrationErrorLog)
        .where(IntegrationErrorLog.provider == i.provider)
        .order_by(IntegrationErrorLog.created_at.desc()).limit(5)
    )).all()
    return IntegrationOut(
        provider=i.provider, title=i.title, channel=i.channel,
        status=i.status, reason=_STATUS_REASON.get(i.status, i.status),
        configured_keys=list((i.config or {}).keys()),
        errors=[IntegrationErrorOut.model_validate(e) for e in errors],
    )


@router.get("/integrations", response_model=list[IntegrationOut])
async def list_integrations(db: AsyncSession = Depends(get_db)):
    rows = (await db.scalars(select(Integration).order_by(Integration.id))).all()
    return [await _integration_out(db, i) for i in rows]


@router.post("/integrations/{provider}/connect", response_model=IntegrationOut)
async def connect_integration(provider: str, payload: IntegrationIn,
                              db: AsyncSession = Depends(get_db)):
    integration = await db.scalar(select(Integration).where(Integration.provider == provider))
    if not integration:
        raise HTTPException(404, "Провайдер не найден")
    integration.config = payload.config
    integration.status = "connected"
    await db.commit()
    return await _integration_out(db, integration)


@router.post("/integrations/{provider}/disconnect", response_model=IntegrationOut)
async def disconnect_integration(provider: str, db: AsyncSession = Depends(get_db)):
    integration = await db.scalar(select(Integration).where(Integration.provider == provider))
    if not integration:
        raise HTTPException(404, "Провайдер не найден")
    integration.config = {}
    integration.status = "setup_required"
    await db.commit()
    return await _integration_out(db, integration)


# ---------- Каскады ----------
@router.get("/cascades", response_model=list[CascadeOut])
async def list_cascades(db: AsyncSession = Depends(get_db)):
    return (await db.scalars(select(Cascade).order_by(Cascade.id))).all()


@router.post("/cascades", response_model=CascadeOut, status_code=201)
async def create_cascade(payload: CascadeIn, db: AsyncSession = Depends(get_db)):
    for step in payload.steps:
        try:
            get_adapter(step.channel)
        except KeyError:
            raise HTTPException(400, f"Неизвестный канал: {step.channel}")
    cascade = Cascade(name=payload.name, steps=[s.model_dump() for s in payload.steps])
    db.add(cascade)
    await db.commit()
    return cascade


@router.delete("/cascades/{cascade_id}", status_code=204)
async def delete_cascade(cascade_id: int, db: AsyncSession = Depends(get_db)):
    cascade = await db.get(Cascade, cascade_id)
    if not cascade:
        raise HTTPException(404, "Каскад не найден")
    # Отвязываем каскад от кампаний и сообщений: история сохраняется,
    # но ссылочная целостность не нарушается.
    await db.execute(
        update(Campaign).where(Campaign.cascade_id == cascade_id).values(cascade_id=None)
    )
    await db.execute(
        update(Message).where(Message.cascade_id == cascade_id).values(cascade_id=None)
    )
    await db.delete(cascade)
    await db.commit()


# ============================================================
# ФРОНТЕНД
# ============================================================
INDEX_HTML = r"""<!DOCTYPE html>
<html lang="ru" data-theme="dark">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Omni Messenger</title>
<script>
(function(){
  var s = localStorage.getItem("omni-theme") || "dark";
  document.documentElement.setAttribute("data-theme", s);
})();
</script>
<style>
:root, [data-theme="dark"]{
  --bg:#0D1117; --panel:#161B22; --card:#1C2128; --border:#30363D;
  --text:#E6EDF3; --muted:#8B949E;
  --empty:#8B949E;
  --accent:#0066FF; --accent-hover:#0052cc;
  --email:#3B82F6; --sms:#22C55E; --push:#F59E0B; --telegram:#38BDF8;
  --danger:#F85149; --warn:#F59E0B; --ok:#3FB950; --overlay:rgba(0,0,0,.65);
}
[data-theme="light"]{
  --bg:#F8F9FA; --panel:#FFFFFF; --card:#F1F3F5; --border:#D0D7DE;
  --text:#1F2328; --muted:#4A5361;
  --empty:#6E7781;
  --accent:#0066FF; --accent-hover:#0052cc;
  --email:#2563EB; --sms:#16A34A; --push:#D97706; --telegram:#0284C7;
  --danger:#CF222E; --warn:#BF8700; --ok:#1A7F37; --overlay:rgba(15,23,42,.35);
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,"Segoe UI",Inter,Roboto,sans-serif;
     background:var(--bg);color:var(--text);font-size:14px;
     transition:background .15s,color .15s}
.app{display:grid;grid-template-columns:220px 1fr;min-height:100vh}

.sidebar{background:var(--panel);border-right:1px solid var(--border);
         padding:20px 12px;display:flex;flex-direction:column;gap:24px}
.logo{font-weight:700;font-size:18px;display:flex;align-items:center;gap:8px}
.logo-dot{width:10px;height:10px;border-radius:50%;background:var(--accent)}
.nav-btn{display:flex;align-items:center;gap:10px;width:100%;text-align:left;
         background:none;border:none;color:var(--muted);padding:10px 12px;
         border-radius:8px;cursor:pointer;transition:.15s;font:inherit;font-size:14px}
.nav-btn:hover{background:var(--card);color:var(--text)}
.nav-btn.active{background:var(--accent);color:#fff}
.nav-icon{font-size:16px;width:18px;text-align:center}
.sidebar-footer{margin-top:auto;color:var(--muted);font-size:12px;
                display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block}
.dot-off{background:#555}
.dot-on{background:var(--ok);box-shadow:0 0 8px var(--ok)}
.theme-btn{background:var(--card);color:var(--text);border:1px solid var(--border);
           border-radius:8px;padding:6px 10px;cursor:pointer;font:inherit;
           font-size:12px;transition:.15s}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}

.content{padding:28px 32px;overflow-y:auto}
.section{display:none}
.section.active{display:block}
.page-head{display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap}
.page-head h1{font-size:22px;font-weight:600}
.page-head .muted{margin-left:auto}
.muted{color:var(--muted);font-size:13px}
.panel{background:var(--panel);border:1px solid var(--border);border-radius:12px;padding:18px}
.panel h2{font-size:13px;font-weight:600;margin-bottom:14px;
          color:var(--muted);text-transform:uppercase;letter-spacing:.5px}

/* ---------- Дашборд ---------- */
.dash-grid{display:grid;grid-template-columns:1fr 340px;gap:18px;align-items:start}
.messages{display:flex;flex-direction:column;gap:8px;max-height:65vh;overflow-y:auto}
.msg-row{display:grid;grid-template-columns:24px 1fr auto auto auto;gap:12px;
         align-items:center;padding:10px 12px;border-radius:8px;background:var(--card);
         cursor:pointer;transition:.15s}
.msg-row:hover{background:var(--border)}
.msg-ch{font-size:16px}
.msg-name{font-weight:500}
.msg-body{color:var(--muted);font-size:12px;overflow:hidden;
          text-overflow:ellipsis;white-space:nowrap}
.msg-time{color:var(--muted);font-size:12px}
.badge{padding:3px 9px;border-radius:99px;font-size:11px;font-weight:600;cursor:help}
.badge.delivered,.badge.read{background:rgba(34,197,94,.15);color:var(--ok)}
.badge.sent{background:rgba(59,130,246,.15);color:var(--email)}
.badge.queued{background:rgba(139,148,158,.15);color:var(--muted)}
.badge.failed{background:rgba(239,68,68,.18);color:var(--danger)}
.btn-mini{padding:3px 8px;background:transparent;border:1px solid var(--border);
          color:var(--muted);border-radius:6px;cursor:pointer;font:inherit;
          font-size:11px;transition:.15s}
.btn-mini:hover{color:var(--accent);border-color:var(--accent)}
.btn-mini:disabled{opacity:.4;cursor:not-allowed}

.metric-period{font-size:12px;color:var(--muted);margin-bottom:10px;
               display:flex;justify-content:space-between;align-items:center;gap:8px}
.stat-cards{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:14px}
.stat-card{background:var(--card);border-radius:10px;padding:12px}
.stat-card .value{font-size:22px;font-weight:700}
.stat-card .value .secondary{font-size:14px;color:var(--muted);font-weight:400}
.stat-card .label{font-size:11px;color:var(--muted);margin-top:2px}
.stat-card .delta{font-size:11px;margin-top:4px}
.stat-card .delta.up{color:var(--ok)}
.stat-card .delta.down{color:var(--danger)}
.stat-card .delta.neutral{color:var(--muted)}
.small-note{font-size:11px;color:var(--muted);margin-top:8px;
            padding:6px 10px;border-left:2px solid var(--warn);
            background:rgba(245,158,11,.1);border-radius:4px;line-height:1.5}
.chart-box{margin-top:10px;background:var(--card);border-radius:8px;padding:10px}
.chart-box svg{display:block;width:100%;height:40px}
.chart-label{font-size:11px;color:var(--muted);margin-bottom:4px}
.chart-empty{padding:14px;text-align:center;font-size:12px;color:var(--muted);line-height:1.5}
.channel-status{display:flex;flex-direction:column;gap:8px}
.ch-row{display:flex;justify-content:space-between;align-items:center;font-size:13px}

/* ---------- Композер ---------- */
.composer{display:grid;grid-template-columns:1fr 380px;gap:18px;align-items:start}
.panel-group{display:flex;flex-direction:column;gap:18px}
.group-title{font-size:12px;font-weight:600;color:var(--muted);
             text-transform:uppercase;letter-spacing:.5px;
             padding-bottom:10px;border-bottom:1px solid var(--border);
             margin-bottom:12px}
.label{display:block;font-size:12px;color:var(--muted);margin:14px 0 6px}
.label .req{color:var(--danger);margin-left:4px}
.label .counter{float:right;font-size:11px;opacity:.8}
.field-error{color:var(--danger);font-size:12px;margin-top:6px;display:none}
.field-error.show{display:block}
.hint{font-size:12px;color:var(--muted);margin-top:8px;line-height:1.5;
      padding:8px 10px;background:var(--card);border-left:2px solid var(--accent);
      border-radius:4px}
.hint strong{color:var(--text)}
.input{width:100%;background:var(--card);border:1px solid var(--border);
       border-radius:8px;padding:10px 12px;color:var(--text);font:inherit;outline:none;
       transition:background .15s,border-color .15s}
.input:focus{border-color:var(--accent)}
.textarea{min-height:130px;resize:vertical}
.picker{display:flex;flex-wrap:wrap;gap:8px;max-height:130px;overflow-y:auto}
.pick{padding:6px 12px;border-radius:99px;background:var(--card);
      border:1px solid var(--border);cursor:pointer;font-size:13px}
.pick.on{border-color:var(--accent);background:rgba(0,102,255,.15)}
.chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{padding:8px 14px;border-radius:99px;background:var(--card);
      border:1px solid var(--border);cursor:pointer;font-size:13px;transition:.15s}
.chip.on{border-color:currentColor}
.chip[data-ch="email"].on{color:var(--email);background:rgba(59,130,246,.15)}
.chip[data-ch="sms"].on{color:var(--sms);background:rgba(34,197,94,.15)}
.chip[data-ch="push"].on{color:var(--push);background:rgba(245,158,11,.15)}
.chip[data-ch="telegram"].on{color:var(--telegram);background:rgba(56,189,248,.15)}

.mode-switch{display:flex;gap:8px;margin-bottom:6px}
.mode-btn{flex:1;padding:10px;border-radius:8px;border:1px solid var(--border);
          background:var(--card);color:var(--muted);cursor:pointer;font:inherit;
          font-size:13px;transition:.15s}
.mode-btn.on{border-color:var(--accent);color:var(--accent);
             background:rgba(0,102,255,.1);font-weight:600}

.sms-counter{margin-top:8px;font-size:12px;color:var(--muted)}
.sms-counter.warn{color:var(--warn)}
.btn-primary{margin-top:16px;width:100%;padding:12px;background:var(--accent);
             color:#fff;border:none;border-radius:8px;cursor:pointer;
             font:inherit;font-size:14px;font-weight:600;transition:.15s;
             display:flex;align-items:center;justify-content:center;gap:8px}
.btn-primary:hover:not(:disabled){background:var(--accent-hover)}
.btn-primary:disabled{opacity:.6;cursor:not-allowed}
.btn-primary.danger{background:var(--danger)}
.btn-primary.danger:hover:not(:disabled){background:#B91C1C}
.btn-primary .spinner{width:14px;height:14px;border:2px solid rgba(255,255,255,.35);
                       border-top-color:#fff;border-radius:50%;
                       animation:spin .7s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.btn-ghost{margin-top:10px;padding:8px 14px;background:transparent;color:var(--muted);
           border:1px dashed var(--border);border-radius:8px;cursor:pointer;
           font:inherit;font-size:13px}
.btn-ghost:hover{color:var(--accent);border-color:var(--accent)}
.btn-ghost.danger{color:var(--danger);border-color:var(--danger)}
.btn-ghost.danger:hover{background:rgba(248,81,73,.08)}

.preview{display:flex;flex-direction:column;gap:14px}
.pv{border-radius:12px;padding:12px;background:var(--card);border-left:3px solid}
.pv-email{border-color:var(--email)}
.pv-sms{border-color:var(--sms)}
.pv-push{border-color:var(--push)}
.pv-telegram{border-color:var(--telegram)}
.pv-head{font-size:11px;color:var(--muted);margin-bottom:6px;text-transform:uppercase}

/* ============================================================
   КОНТАКТЫ
   ============================================================ */
.contacts-toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
                  margin-bottom:14px}
.contacts-toolbar .input{flex:1;min-width:220px}

.filter-chips{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.filter-chip{padding:6px 12px;border-radius:99px;background:var(--card);
             border:1px solid var(--border);cursor:pointer;font-size:12px;
             color:var(--muted);transition:.15s;display:flex;align-items:center;gap:6px}
.filter-chip:hover{border-color:var(--accent);color:var(--text)}
.filter-chip.on{border-color:var(--accent);color:var(--accent);
                background:rgba(0,102,255,.12);font-weight:600}
.filter-chip .count{font-size:11px;opacity:.85;
                    background:var(--panel);border-radius:99px;padding:1px 6px}
.filter-chip.on .count{background:rgba(0,102,255,.2)}
.filter-clear{background:transparent;border:none;color:var(--danger);
              cursor:pointer;font:inherit;font-size:12px;padding:4px 8px;
              border-radius:6px}
.filter-clear:hover{background:rgba(248,81,73,.1)}

.result-count{font-size:12px;color:var(--muted);margin-bottom:10px}

.bulk-toolbar{display:flex;gap:10px;align-items:center;
              background:rgba(0,102,255,.1);border:1px solid var(--accent);
              border-radius:8px;padding:10px 14px;margin-bottom:12px;font-size:13px}
.bulk-toolbar .btn-ghost{margin:0;padding:6px 12px;font-size:12px}

.contacts{margin-top:6px;display:flex;flex-direction:column;gap:6px}
.contacts-head{display:grid;
               grid-template-columns:28px 1.2fr 1fr 1fr 1fr 100px 80px;
               gap:10px;padding:0 10px;font-size:11px;color:var(--muted);
               text-transform:uppercase;letter-spacing:.5px;align-items:center;
               margin-bottom:6px}
.contact-row{display:grid;
             grid-template-columns:28px 1.2fr 1fr 1fr 1fr 100px 80px;
             gap:10px;align-items:center;padding:10px;background:var(--card);
             border-radius:8px;font-size:13px}
.contact-row.selected{background:rgba(0,102,255,.08);
                      box-shadow:inset 2px 0 0 var(--accent)}
.contact-row .empty{color:var(--empty);font-style:italic}
.contact-row .channels-cell{display:flex;gap:2px;font-size:14px;cursor:help}
.contact-row .actions{display:flex;gap:4px;justify-content:flex-end}
.btn-icon{background:transparent;border:none;cursor:pointer;font-size:14px;
          padding:4px 8px;border-radius:6px;color:var(--muted);transition:.15s;
          line-height:1}
.btn-icon:hover{background:var(--panel);color:var(--text)}
.btn-icon.danger:hover{color:var(--danger)}

.cb{appearance:none;width:16px;height:16px;border:1.5px solid var(--border);
    border-radius:4px;background:transparent;cursor:pointer;position:relative;
    transition:.15s;flex-shrink:0}
.cb:hover{border-color:var(--accent)}
.cb:checked,.cb:indeterminate{background:var(--accent);border-color:var(--accent)}
.cb:checked::after{content:"";position:absolute;left:4px;top:1px;
                   width:5px;height:9px;border:solid #fff;border-width:0 2px 2px 0;
                   transform:rotate(45deg)}
.cb:indeterminate::after{content:"";position:absolute;left:3px;top:6px;
                         width:8px;height:2px;background:#fff}
.cb:disabled{opacity:.4;cursor:not-allowed}

.pagination-bar{display:flex;justify-content:space-between;align-items:center;
                margin-top:14px;padding-top:14px;
                border-top:1px solid var(--border);gap:12px;flex-wrap:wrap}
.pagination-controls{display:flex;gap:8px;align-items:center}
.pagination-controls .input{width:auto;padding:6px 10px;font-size:12px}
.page-btn{padding:6px 10px;background:var(--card);border:1px solid var(--border);
          color:var(--text);border-radius:6px;cursor:pointer;font:inherit;
          font-size:13px;min-width:32px}
.page-btn:hover:not(:disabled){border-color:var(--accent);color:var(--accent)}
.page-btn:disabled{opacity:.4;cursor:not-allowed}
.page-num{padding:6px 10px;background:transparent;border:none;color:var(--text);
          border-radius:6px;cursor:pointer;font:inherit;font-size:13px;min-width:32px}
.page-num:hover{background:var(--card)}
.page-num.on{background:var(--accent);color:#fff;font-weight:600}

/* ---------- Футер секции контактов: центрированная кнопка ---------- */
.contacts-footer{margin-top:18px;padding-top:18px;
                 border-top:1px solid var(--border);
                 display:flex;flex-direction:column;
                 align-items:center;justify-content:center;
                 gap:8px;text-align:center}
.contacts-footer .btn-primary{margin:0;width:auto;padding:12px 28px;font-size:14px}
.contacts-footer .footer-hint{font-size:12px;color:var(--muted);line-height:1.4}

.empty-state{padding:30px;text-align:center;color:var(--muted);font-size:13px;line-height:1.6}

/* ---------- Каскады ---------- */
.steps{display:flex;flex-direction:column;gap:8px;margin-top:12px}
.step-row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.cascade-layout{display:grid;grid-template-columns:1fr 260px;gap:18px;align-items:start}
.cascade-preview{background:var(--card);border-radius:10px;padding:14px;
                 display:flex;flex-direction:column;align-items:center;gap:8px}
.cascade-node{display:flex;align-items:center;gap:8px;padding:8px 14px;
              background:var(--panel);border-radius:8px;font-size:13px;
              border:1px solid var(--border);width:100%}
.cascade-arrow{color:var(--muted);font-size:14px}
.cascade-meta{font-size:11px;color:var(--muted);text-align:center}
.cascades-list{margin-top:18px;display:flex;flex-direction:column;gap:10px}
.cascade-card{background:var(--panel);border:1px solid var(--border);
              border-radius:10px;padding:14px}
.cascade-flow{color:var(--muted);font-size:13px;margin-top:8px;line-height:1.6}
.cascade-flow strong{color:var(--text)}
.cascade-card-head{display:flex;justify-content:space-between;
                   align-items:flex-start;gap:10px}

/* ---------- Интеграции ---------- */
.integrations{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px}
.int-card{background:var(--panel);border:1px solid var(--border);border-radius:12px;
          padding:16px;display:flex;flex-direction:column;gap:10px}
.int-title{font-weight:600;font-size:15px}
.int-status{font-size:12px;font-weight:600}
.int-status.connected{color:var(--ok)}
.int-status.setup_required{color:var(--warn)}
.int-status.auth_error,.int-status.rate_limited{color:var(--danger)}
.int-status.needs_refresh{color:var(--warn)}
.int-reason{font-size:12px;color:var(--muted);line-height:1.5}
.int-errors{font-size:11px;color:var(--muted);background:var(--card);
            border-radius:6px;padding:8px;max-height:100px;overflow-y:auto}
.int-errors div{padding:3px 0;border-bottom:1px solid var(--border)}
.int-errors div:last-child{border-bottom:none}

/* ---------- Модалки ---------- */
.modal-backdrop{position:fixed;inset:0;background:var(--overlay);
                display:none;align-items:center;justify-content:center;z-index:100}
.modal-backdrop.open{display:flex}
.modal{background:var(--panel);border:1px solid var(--border);border-radius:12px;
       padding:20px;width:min(680px,92vw);max-height:85vh;
       display:flex;flex-direction:column;gap:14px}
.modal.wide{width:min(820px,94vw)}
.modal-head{display:flex;justify-content:space-between;align-items:center;
            border-bottom:1px solid var(--border);padding-bottom:12px}
.modal-head h3{font-size:16px;font-weight:600}
.modal-close{background:transparent;border:none;color:var(--muted);font-size:22px;
             cursor:pointer;padding:0 6px;border-radius:6px;line-height:1}
.modal-close:hover{background:var(--card);color:var(--text)}
.modal-body{overflow-y:auto;display:flex;flex-direction:column;gap:12px}
.modal-actions{display:flex;gap:8px;justify-content:flex-end;
               border-top:1px solid var(--border);padding-top:12px}

.msg-detail dl{display:grid;grid-template-columns:120px 1fr;gap:6px 12px;font-size:13px}
.msg-detail dt{color:var(--muted)}
.msg-detail dd{color:var(--text);word-break:break-word}
.msg-detail .body-box{background:var(--card);padding:12px;border-radius:8px;
                      white-space:pre-wrap;line-height:1.5;font-size:13px;margin-top:6px}
.msg-detail .error-box{background:rgba(239,68,68,.1);color:var(--danger);
                       padding:10px 12px;border-radius:8px;font-size:12px;
                       border-left:3px solid var(--danger);line-height:1.5}

/* ---------- Тосты ---------- */
.toast-container{position:fixed;bottom:20px;right:20px;z-index:200;
                 display:flex;flex-direction:column;gap:8px;max-width:380px}
.toast{padding:12px 18px;border-radius:8px;background:var(--panel);
       border:1px solid var(--border);color:var(--text);font-size:13px;
       box-shadow:0 8px 24px rgba(0,0,0,.25);animation:slideIn .2s ease-out;
       line-height:1.4}
.toast.success{border-color:var(--ok)}
.toast.error{border-color:var(--danger)}
.toast.info{border-color:var(--accent)}
@keyframes slideIn{from{opacity:0;transform:translateX(20px)}to{opacity:1;transform:none}}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="logo"><span class="logo-dot"></span> Omni</div>
    <nav>
      <button class="nav-btn active" data-section="dashboard" title="Дашборд">
        <span class="nav-icon">▦</span><span>Дашборд</span></button>
      <button class="nav-btn" data-section="composer" title="Создать сообщение">
        <span class="nav-icon">✎</span><span>Создать</span></button>
      <button class="nav-btn" data-section="contacts" title="Контакты">
        <span class="nav-icon">◍</span><span>Контакты</span></button>
      <button class="nav-btn" data-section="cascades" title="Каскадные сценарии">
        <span class="nav-icon">⇄</span><span>Каскады</span></button>
      <button class="nav-btn" data-section="integrations" title="Интеграции">
        <span class="nav-icon">⚙</span><span>Интеграции</span></button>
    </nav>
    <div class="sidebar-footer">
      <button id="theme-toggle" class="theme-btn" title="Переключить тему">☀ Светлая</button>
      <span title="Статус real-time соединения">
        <span id="ws-status" class="dot dot-off"></span> real-time
      </span>
    </div>
  </aside>

  <main class="content">
    <!-- ДАШБОРД -->
    <section id="sec-dashboard" class="section active">
      <header class="page-head">
        <h1>Дашборд</h1>
        <span class="muted">Клик по сообщению — открыть полный текст</span>
      </header>
      <div class="dash-grid">
        <div class="panel">
          <h2>Последние сообщения</h2>
          <div id="messages-list" class="messages"></div>
        </div>
        <div class="panel">
          <div class="metric-period">
            <span id="period-label">за последние 24 часа</span>
            <span title="Скользящее окно 24 часа. При выборке меньше 10 сообщений проценты не показываются.">ⓘ</span>
          </div>
          <div id="stat-cards" class="stat-cards"></div>
          <div id="small-note" class="small-note" style="display:none">
            Выборка меньше 10 сообщений — проценты не показываются.
          </div>
          <div id="sparkline" class="chart-box"></div>
          <h2 style="margin-top:18px">Каналы</h2>
          <div id="channel-status" class="channel-status"></div>
        </div>
      </div>
    </section>

    <!-- КОМПОЗЕР -->
    <section id="sec-composer" class="section">
      <header class="page-head"><h1>Новое сообщение</h1></header>
      <div class="composer">
        <div class="panel-group">
          <div class="panel">
            <div class="group-title">Получатели</div>
            <label class="label">Кому<span class="req">*</span></label>
            <div id="contact-picker" class="picker"></div>
            <div id="err-contacts" class="field-error">Выберите хотя бы одного получателя</div>
          </div>

          <div class="panel">
            <div class="group-title">Способ отправки</div>
            <div class="mode-switch">
              <button class="mode-btn on" data-mode="direct">По каналам</button>
              <button class="mode-btn" data-mode="cascade">По каскаду</button>
            </div>
            <div id="mode-direct">
              <label class="label">Каналы отправки<span class="req">*</span></label>
              <div id="channel-chips" class="chips"></div>
              <div id="err-channels" class="field-error">Укажите хотя бы один канал</div>
            </div>
            <div id="mode-cascade" style="display:none">
              <label class="label">Готовый сценарий<span class="req">*</span></label>
              <select id="cascade-select" class="input">
                <option value="">— выберите каскад —</option>
              </select>
              <div id="err-cascade" class="field-error">Выберите каскад</div>
              <div class="hint">
                <strong>Как это работает:</strong> сообщение отправится по цепочке
                каналов. Если доставка не подтвердится за отведённое время,
                система перейдёт к следующему.
              </div>
            </div>
          </div>

          <div class="panel">
            <div class="group-title">Содержание</div>
            <label class="label">Тема / заголовок</label>
            <input id="in-subject" class="input" maxlength="255"
                   placeholder="Заголовок (для Email и Push)">
            <label class="label">
              Текст<span class="req">*</span>
              <span class="counter" id="body-counter">0 / 4096</span>
            </label>
            <textarea id="in-body" class="input textarea" maxlength="4096"
              placeholder="Напишите текст — система адаптирует его под каждый канал"></textarea>
            <div id="err-body" class="field-error">Введите текст сообщения</div>
            <div class="hint">
              <strong>Как адаптируется текст:</strong> Email получает полный текст
              с темой; SMS обрезается до 160 символов (или разбивается на части);
              Push — до 240; Telegram — до 4096.
            </div>
            <div id="sms-counter" class="sms-counter"></div>
            <button id="btn-send" class="btn-primary">
              <span class="btn-label">Отправить</span>
            </button>
          </div>
        </div>

        <div class="panel">
          <h2>Живое превью</h2>
          <div id="preview" class="preview"></div>
        </div>
      </div>
    </section>

    <!-- КОНТАКТЫ -->
    <section id="sec-contacts" class="section">
      <header class="page-head">
        <h1>Контакты</h1>
      </header>

      <div class="panel">
        <div class="contacts-toolbar">
          <input id="contact-search" class="input"
                 placeholder="Поиск по имени, email, телефону, Telegram…"
                 title="Поиск работает по всем полям контакта">
        </div>

        <div class="filter-chips" id="filter-chips">
          <button class="filter-chip on" data-filter="">
            Все <span class="count" id="cnt-all">0</span>
          </button>
          <button class="filter-chip" data-filter="email">
            📧 С Email <span class="count" id="cnt-email">0</span>
          </button>
          <button class="filter-chip" data-filter="phone">
            💬 С телефоном <span class="count" id="cnt-phone">0</span>
          </button>
          <button class="filter-chip" data-filter="telegram">
            ✈️ С Telegram <span class="count" id="cnt-telegram">0</span>
          </button>
          <button class="filter-clear" id="filter-clear" style="display:none"
                  title="Сбросить поиск и фильтры">✕ Сбросить</button>
        </div>

        <div class="result-count" id="result-count"></div>

        <div class="bulk-toolbar" id="bulk-toolbar" style="display:none">
          <span>Выбрано: <strong id="bulk-count">0</strong></span>
          <button class="btn-ghost" id="bulk-clear" style="margin-left:auto">Снять выбор</button>
          <button class="btn-ghost danger" id="bulk-delete">Удалить выбранные</button>
        </div>

        <div class="contacts-head">
          <input type="checkbox" id="select-all-page" class="cb"
                 title="Выбрать все на текущей странице">
          <span>Имя</span>
          <span>Email</span>
          <span>Телефон</span>
          <span>Telegram</span>
          <span title="Каналы, по которым можно отправить сообщение этому контакту">
            Каналы
          </span>
          <span></span>
        </div>
        <div id="contacts-table" class="contacts"></div>

        <div class="pagination-bar" id="pagination-bar" style="display:none">
          <span class="muted" id="pagination-info"></span>
          <div class="pagination-controls">
            <span class="muted">На странице:</span>
            <select id="page-size" class="input" title="Сколько строк показывать">
              <option value="20">20</option>
              <option value="50">50</option>
              <option value="100">100</option>
            </select>
            <button class="page-btn" id="page-prev" title="Предыдущая страница">‹</button>
            <span id="page-numbers" style="display:flex;gap:4px"></span>
            <button class="page-btn" id="page-next" title="Следующая страница">›</button>
          </div>
        </div>

        <!-- Футер секции: центрированная кнопка добавления контакта -->
        <div class="contacts-footer">
          <button id="btn-open-add-contact" class="btn-primary">
            <span class="btn-label">+ Добавить контакт</span>
          </button>
          <span class="footer-hint">Новый контакт появится в конце списка</span>
        </div>
      </div>
    </section>

    <!-- КАСКАДЫ -->
    <section id="sec-cascades" class="section">
      <header class="page-head"><h1>Каскадные сценарии</h1></header>
      <div class="panel">
        <label class="label">Название сценария<span class="req">*</span></label>
        <input id="cascade-name" class="input" maxlength="150"
               placeholder="Например: Push → Telegram → SMS">
        <div class="hint">
          <strong>Таймаут ожидания доставки</strong> — сколько секунд ждать
          подтверждения, прежде чем перейти к следующему каналу.
          Допустимо от 1 до 300 секунд.
        </div>
        <div class="cascade-layout" style="margin-top:14px">
          <div>
            <div id="cascade-steps" class="steps"></div>
            <button id="btn-add-step" class="btn-ghost">+ шаг</button>
            <div id="err-cascade-form" class="field-error">Добавьте хотя бы один шаг</div>
            <button id="btn-save-cascade" class="btn-primary">
              <span class="btn-label">Сохранить каскад</span>
            </button>
          </div>
          <div class="cascade-preview" id="cascade-preview">
            <div class="cascade-meta">Предпросмотр цепочки</div>
          </div>
        </div>
      </div>
      <div id="cascades-list" class="cascades-list"></div>
    </section>

    <!-- ИНТЕГРАЦИИ -->
    <section id="sec-integrations" class="section">
      <header class="page-head"><h1>Интеграции</h1></header>
      <div id="integrations-grid" class="integrations"></div>
    </section>
  </main>
</div>

<!-- Модалка: Новый контакт -->
<div id="contact-modal" class="modal-backdrop">
  <div class="modal">
    <div class="modal-head">
      <h3>Новый контакт</h3>
      <button class="modal-close" data-close="contact-modal">×</button>
    </div>
    <div class="modal-body">
      <label class="label">Имя<span class="req">*</span></label>
      <input id="c-name" class="input" placeholder="Иван Иванов" maxlength="150">
      <div id="c-name-err" class="field-error">Укажите имя контакта</div>

      <label class="label">Email</label>
      <input id="c-email" class="input" placeholder="ivan@example.com" maxlength="255"
             type="email">

      <label class="label">Телефон</label>
      <input id="c-phone" class="input" placeholder="+79001234567" maxlength="32">

      <label class="label">Telegram ID</label>
      <input id="c-tg" class="input" placeholder="100200300" maxlength="64">
    </div>
    <div class="modal-actions">
      <button class="btn-ghost" data-close="contact-modal" style="margin:0">Отмена</button>
      <button id="btn-add-contact" class="btn-primary"
              style="margin:0;width:auto;padding:10px 18px">
        <span class="btn-label">+ Добавить контакт</span>
      </button>
    </div>
  </div>
</div>

<!-- Модалка: история контакта -->
<div id="history-modal" class="modal-backdrop">
  <div class="modal wide">
    <div class="modal-head">
      <h3 id="history-title">История</h3>
      <button class="modal-close" data-close="history-modal">×</button>
    </div>
    <div id="history-body" class="modal-body"></div>
  </div>
</div>

<!-- Модалка: просмотр сообщения -->
<div id="message-modal" class="modal-backdrop">
  <div class="modal wide">
    <div class="modal-head">
      <h3>Сообщение</h3>
      <button class="modal-close" data-close="message-modal">×</button>
    </div>
    <div id="message-body" class="modal-body"></div>
    <div class="modal-actions">
      <button class="btn-ghost" data-close="message-modal" style="margin:0">Закрыть</button>
      <button id="btn-retry" class="btn-primary"
              style="margin:0;width:auto;padding:10px 18px;display:none">
        <span class="btn-label">Повторить отправку</span>
      </button>
    </div>
  </div>
</div>

<!-- Модалка: подтверждение -->
<div id="confirm-modal" class="modal-backdrop">
  <div class="modal">
    <div class="modal-head">
      <h3 id="confirm-title">Подтверждение</h3>
      <button class="modal-close" data-close="confirm-modal">×</button>
    </div>
    <div id="confirm-text" class="modal-body"></div>
    <div class="modal-actions">
      <button class="btn-ghost" data-close="confirm-modal" style="margin:0">Отмена</button>
      <button id="confirm-yes" class="btn-primary danger"
              style="margin:0;width:auto;padding:10px 18px">
        <span class="btn-label">Удалить</span>
      </button>
    </div>
  </div>
</div>

<div id="toast-container" class="toast-container"></div>

<script>
const state = {
  channels: [],
  contacts: [],
  cascades: [],
  selectedContacts: new Set(),
  selectedChannels: new Set(["email"]),
  sendMode: "direct",
  search: "",
  filter: "",
  contactsPage: 1,
  contactsPageSize: 20,
  selectedContactIds: new Set(),
  currentMessageId: null,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const STATUS_LABEL = {
  queued:"В очереди", sent:"Отправлено", delivered:"Доставлено",
  read:"Прочитано", failed:"Ошибка"
};
const STATUS_HINT = {
  queued:"Сообщение в очереди.",
  sent:"Передано в канал, ждём подтверждения.",
  delivered:"Доставлено получателю.",
  read:"Получатель прочитал сообщение.",
  failed:"Доставка не удалась. Можно повторить отправку.",
};

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"
  }[c]));
}
async function api(path, options = {}) {
  const res = await fetch("/api" + path, {
    headers: { "Content-Type": "application/json" }, ...options,
  });
  if (!res.ok) throw new Error(res.status + " " + (await res.text()));
  return res.status === 204 ? null : res.json();
}
function channelByKey(key) {
  return state.channels.find(c => c.key === key)
    || { emoji:"•", title:key, color:"#888" };
}
function toast(message, type = "success") {
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = message;
  $("#toast-container").appendChild(el);
  setTimeout(() => el.remove(), 3500);
}
async function withLoading(btn, fn) {
  if (btn.disabled) return;
  const label = btn.querySelector(".btn-label") || btn;
  const original = label.textContent;
  btn.disabled = true;
  label.innerHTML = `<span class="spinner"></span> Подождите…`;
  try { await fn(); }
  finally { btn.disabled = false; label.textContent = original; }
}

/* ---------- Модалки ---------- */
function openModal(id) { $("#" + id).classList.add("open"); }
function closeModal(id) { $("#" + id).classList.remove("open"); }
document.querySelectorAll("[data-close]").forEach(el => {
  el.addEventListener("click", () => closeModal(el.dataset.close));
});
document.querySelectorAll(".modal-backdrop").forEach(el => {
  el.addEventListener("click", (e) => {
    if (e.target === el) el.classList.remove("open");
  });
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape")
    document.querySelectorAll(".modal-backdrop.open").forEach(m => m.classList.remove("open"));
});
function confirmDialog(title, text, onYes) {
  $("#confirm-title").textContent = title;
  $("#confirm-text").textContent = text;
  const old = $("#confirm-yes");
  const fresh = old.cloneNode(true);
  old.parentNode.replaceChild(fresh, old);
  fresh.addEventListener("click", async () => {
    closeModal("confirm-modal");
    await onYes();
  });
  openModal("confirm-modal");
}

/* ---------- Тема ---------- */
function applyTheme(theme) {
  document.documentElement.setAttribute("data-theme", theme);
  localStorage.setItem("omni-theme", theme);
  const btn = $("#theme-toggle");
  if (btn) btn.textContent = theme === "light" ? "☾ Тёмная" : "☀ Светлая";
}
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") || "dark";
  applyTheme(cur === "light" ? "dark" : "light");
}

/* ---------- Навигация ---------- */
$$(".nav-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    $$(".nav-btn").forEach(b => b.classList.remove("active"));
    $$(".section").forEach(s => s.classList.remove("active"));
    btn.classList.add("active");
    $("#sec-" + btn.dataset.section).classList.add("active");
  });
});

/* ============================================================
   ДАШБОРД
   ============================================================ */
function renderSparkline(hourly, hasData) {
  if (!hasData || !hourly || hourly.every(v => v === 0)) {
    return `<div class="chart-empty">
      Недостаточно данных для графика.<br>
      Отправьте несколько сообщений, чтобы увидеть динамику.
    </div>`;
  }
  const max = Math.max(...hourly, 1);
  const w = 280, h = 40;
  const step = w / (hourly.length - 1);
  const pts = hourly.map((v, i) =>
    `${(i * step).toFixed(1)},${(h - (v / max) * (h - 2)).toFixed(1)}`
  ).join(" ");
  return `<div class="chart-label">Доставки по часам</div>
    <svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
      <polyline points="${pts}" fill="none" stroke="var(--ok)" stroke-width="2"
                stroke-linejoin="round" stroke-linecap="round"/>
    </svg>`;
}
function fmtDelta(delta, inverse) {
  if (delta === 0) return `<div class="delta neutral">= без изменений</div>`;
  const positive = inverse ? delta < 0 : delta > 0;
  const cls = positive ? "up" : "down";
  const arrow = delta > 0 ? "▲" : "▼";
  return `<div class="delta ${cls}">${arrow} ${Math.abs(delta)}% к пред. периоду</div>`;
}
async function loadDashboard() {
  const [messages, summary] = await Promise.all([
    api("/messages?limit=30"), api("/analytics/summary"),
  ]);
  $("#messages-list").innerHTML = messages.map(m => {
    const ch = channelByKey(m.channel);
    const time = m.created_at
      ? new Date(m.created_at + "Z").toLocaleTimeString("ru-RU") : "";
    const retryBtn = m.retryable
      ? `<button class="btn-mini" data-retry="${m.id}" title="Повторить отправку">↻</button>`
      : `<span></span>`;
    return `<div class="msg-row" data-msg-id="${m.id}">
      <span class="msg-ch">${ch.emoji}</span>
      <div>
        <div class="msg-name">${escapeHtml(m.contact)} <span class="msg-time">· ${escapeHtml(m.subject||"без темы")}</span></div>
        <div class="msg-body">${escapeHtml(m.body||"")}${m.error ? " — " + escapeHtml(m.error) : ""}</div>
      </div>
      <span class="msg-time">${time}</span>
      <span class="badge ${m.status}" title="${escapeHtml(STATUS_HINT[m.status]||"")}">${STATUS_LABEL[m.status]||m.status}</span>
      ${retryBtn}
    </div>`;
  }).join("") || `<div class="empty-state">Пока пусто — отправьте первое сообщение</div>`;

  $("#period-label").textContent = "скользящие 24 часа";
  const small = summary.is_small_sample;
  const renderMetric = (label, count, rate, delta, inverse) => {
    if (small) {
      return `<div class="stat-card">
        <div class="value">${count}</div>
        <div class="label">${label}</div></div>`;
    }
    return `<div class="stat-card">
      <div class="value">${count} <span class="secondary">(${rate}%)</span></div>
      <div class="label">${label}</div>
      ${fmtDelta(delta, inverse)}</div>`;
  };
  $("#stat-cards").innerHTML = `
    <div class="stat-card">
      <div class="value">${summary.total}</div>
      <div class="label">Сообщений за период</div>
    </div>
    ${renderMetric("Доставлено", summary.delivered_count, summary.delivery_rate,
                    summary.delivery_delta, false)}
    ${renderMetric("Ошибок", summary.failed_count, summary.failure_rate,
                    summary.failure_delta, true)}
    <div class="stat-card">
      <div class="value">${summary.by_status.delivered || 0}</div>
      <div class="label">Подтверждено доставкой</div>
    </div>`;
  $("#small-note").style.display = small ? "block" : "none";
  $("#sparkline").innerHTML = renderSparkline(summary.hourly_delivered,
                                              summary.has_chart_data);
  $("#channel-status").innerHTML = state.channels.map(c => {
    const n = summary.by_channel[c.key] || 0;
    return `<div class="ch-row"><span>${c.emoji} ${c.title}</span>
      <span class="badge ${n?"sent":"queued"}">${n}</span></div>`;
  }).join("");
}
$("#messages-list").addEventListener("click", (e) => {
  const retry = e.target.closest("[data-retry]");
  if (retry) { e.stopPropagation(); retryMessage(Number(retry.dataset.retry)); return; }
  const row = e.target.closest("[data-msg-id]");
  if (row) openMessageDetail(Number(row.dataset.msgId));
});
async function openMessageDetail(id) {
  state.currentMessageId = id;
  $("#message-body").innerHTML = `<div class="empty-state">Загрузка…</div>`;
  openModal("message-modal");
  try {
    const m = await api(`/messages/${id}`);
    const ch = channelByKey(m.channel);
    const time = (iso) => iso ? new Date(iso + "Z").toLocaleString("ru-RU") : "—";
    $("#btn-retry").style.display = m.retryable ? "flex" : "none";
    $("#message-body").innerHTML = `
      <div class="msg-detail">
        <dl>
          <dt>Получатель</dt><dd>${escapeHtml(m.contact||"—")}</dd>
          <dt>Канал</dt><dd>${ch.emoji} ${ch.title}</dd>
          <dt>Статус</dt><dd><span class="badge ${m.status}">${STATUS_LABEL[m.status]||m.status}</span></dd>
          <dt>Шаг каскада</dt><dd>${m.step_index + 1}</dd>
          <dt>Создано</dt><dd>${time(m.created_at)}</dd>
          <dt>Обновлено</dt><dd>${time(m.updated_at)}</dd>
          <dt>Доставлено</dt><dd>${time(m.delivered_at)}</dd>
          ${m.subject ? `<dt>Тема</dt><dd>${escapeHtml(m.subject)}</dd>` : ""}
        </dl>
        <div>
          <div class="muted" style="margin-bottom:6px">Текст:</div>
          <div class="body-box">${escapeHtml(m.body || "—")}</div>
        </div>
        ${m.error ? `<div class="error-box"><strong>Ошибка:</strong> ${escapeHtml(m.error)}</div>` : ""}
      </div>`;
  } catch (e) {
    $("#message-body").innerHTML =
      `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}
async function retryMessage(id) {
  try {
    await api(`/messages/${id}/retry`, { method: "POST" });
    toast("Сообщение поставлено в очередь повторно", "success");
    closeModal("message-modal");
    setTimeout(loadDashboard, 500);
  } catch (e) { toast("Ошибка повтора: " + e.message, "error"); }
}
$("#btn-retry").addEventListener("click", () => {
  if (state.currentMessageId) retryMessage(state.currentMessageId);
});

/* ============================================================
   КОМПОЗЕР
   ============================================================ */
function setMode(mode) {
  state.sendMode = mode;
  $$(".mode-btn").forEach(b => b.classList.toggle("on", b.dataset.mode === mode));
  $("#mode-direct").style.display = mode === "direct" ? "block" : "none";
  $("#mode-cascade").style.display = mode === "cascade" ? "block" : "none";
}
$$(".mode-btn").forEach(btn => {
  btn.addEventListener("click", () => setMode(btn.dataset.mode));
});
function renderComposer() {
  $("#contact-picker").innerHTML = state.contacts.map(c => `
    <div class="pick ${state.selectedContacts.has(c.id)?"on":""}" data-id="${c.id}">
      ${escapeHtml(c.name)}</div>`).join("") ||
    `<div class="muted">Сначала добавьте контакт</div>`;
  $("#contact-picker").querySelectorAll(".pick").forEach(el => {
    el.addEventListener("click", () => {
      const id = Number(el.dataset.id);
      state.selectedContacts.has(id)
        ? state.selectedContacts.delete(id) : state.selectedContacts.add(id);
      el.classList.toggle("on");
      $("#err-contacts").classList.remove("show");
    });
  });
  $("#channel-chips").innerHTML = state.channels.map(c => `
    <div class="chip ${state.selectedChannels.has(c.key)?"on":""}" data-ch="${c.key}">
      ${c.emoji} ${c.title}</div>`).join("");
  $("#channel-chips").querySelectorAll(".chip").forEach(el => {
    el.addEventListener("click", () => {
      const k = el.dataset.ch;
      state.selectedChannels.has(k)
        ? state.selectedChannels.delete(k) : state.selectedChannels.add(k);
      el.classList.toggle("on");
      $("#err-channels").classList.remove("show");
      updatePreview();
    });
  });
  const cur = $("#cascade-select").value;
  $("#cascade-select").innerHTML = `<option value="">— выберите каскад —</option>` +
    state.cascades.map(c =>
      `<option value="${c.id}" ${String(c.id)===cur?"selected":""}>${escapeHtml(c.name)}</option>`
    ).join("");
}
async function updatePreview() {
  const body = $("#in-body").value;
  const subject = $("#in-subject").value;
  $("#body-counter").textContent = `${body.length} / 4096`;
  if (state.selectedChannels.has("sms")) {
    const hasCyr = /[\u0400-\u04FF]/.test(body);
    const single = hasCyr ? 70 : 160;
    const multi = hasCyr ? 67 : 153;
    const parts = body.length <= single ? 1 : Math.ceil(body.length / multi);
    const el = $("#sms-counter");
    el.textContent = `${hasCyr?"UCS-2":"GSM-7"}: ${body.length} симв. · ${parts} SMS`;
    el.classList.toggle("warn", parts > 1);
  } else { $("#sms-counter").textContent = ""; }
  if (!state.selectedChannels.size || state.sendMode !== "direct") {
    $("#preview").innerHTML = `<div class="empty-state">Выберите каналы для превью</div>`;
    return;
  }
  const previews = await api("/composer/preview", {
    method: "POST",
    body: JSON.stringify({ body, subject, channels: [...state.selectedChannels] }),
  });
  $("#preview").innerHTML = previews.map(p => {
    const ch = channelByKey(p.channel);
    let content;
    if (p.channel === "email") {
      content = `<div style="font-weight:600;margin-bottom:6px">${escapeHtml(p.subject||"Без темы")}</div><div>${escapeHtml(p.html)}</div>`;
    } else if (p.channel === "push") {
      content = `<div style="font-weight:600">${escapeHtml(p.title)}</div><div>${escapeHtml(p.text)}</div>`;
    } else { content = escapeHtml(p.text); }
    const meta = p.meta && p.meta.parts
      ? `<div class="pv-head" style="margin-top:6px">${p.meta.parts} SMS · ${p.meta.encoding}</div>` : "";
    return `<div class="pv pv-${p.channel}"><div class="pv-head">${ch.emoji} ${ch.title}</div>${content}${meta}</div>`;
  }).join("");
}
async function sendMessage() {
  let ok = true;
  if (!state.selectedContacts.size) {
    $("#err-contacts").classList.add("show"); ok = false;
  } else $("#err-contacts").classList.remove("show");
  const body = $("#in-body").value.trim();
  if (!body) { $("#err-body").classList.add("show"); ok = false; }
  else $("#err-body").classList.remove("show");
  if (state.sendMode === "direct" && !state.selectedChannels.size) {
    $("#err-channels").classList.add("show"); ok = false;
  } else $("#err-channels").classList.remove("show");
  if (state.sendMode === "cascade" && !$("#cascade-select").value) {
    $("#err-cascade").classList.add("show"); ok = false;
  } else $("#err-cascade").classList.remove("show");
  if (!ok) { toast("Заполните обязательные поля", "error"); return; }

  const payload = {
    contact_ids: [...state.selectedContacts],
    channels: [...state.selectedChannels],
    subject: $("#in-subject").value,
    body,
    cascade_id: state.sendMode === "cascade"
      ? Number($("#cascade-select").value) : null,
  };
  await withLoading($("#btn-send"), async () => {
    try {
      const res = await api("/messages/send", {
        method: "POST", body: JSON.stringify(payload),
      });
      toast(`Отправлено контактов: ${res.queued} · шагов: ${res.steps}`, "success");
      setTimeout(loadDashboard, 500);
    } catch (e) { toast("Ошибка отправки: " + e.message, "error"); }
  });
}

/* ============================================================
   КОНТАКТЫ
   ============================================================ */
function contactsAfterSearch() {
  if (!state.search) return state.contacts;
  const q = state.search.toLowerCase();
  return state.contacts.filter(c =>
    (c.name||"").toLowerCase().includes(q) ||
    (c.email||"").toLowerCase().includes(q) ||
    (c.phone||"").toLowerCase().includes(q) ||
    (c.telegram_id||"").toLowerCase().includes(q));
}
function updateFilterCounts() {
  const pool = contactsAfterSearch();
  $("#cnt-all").textContent = pool.length;
  $("#cnt-email").textContent = pool.filter(c => c.email).length;
  $("#cnt-phone").textContent = pool.filter(c => c.phone).length;
  $("#cnt-telegram").textContent = pool.filter(c => c.telegram_id).length;
  $$(".filter-chip").forEach(b => {
    b.classList.toggle("on", b.dataset.filter === state.filter);
  });
  const active = state.search || state.filter;
  $("#filter-clear").style.display = active ? "inline-block" : "none";
}
function applyFilter(list) {
  if (!state.filter) return list;
  return list.filter(c => !!c[state.filter]);
}
function channelsOf(c) {
  const arr = [];
  if (c.email) arr.push({ key: "email", title: "Email" });
  if (c.phone) arr.push({ key: "sms", title: "SMS (телефон)" });
  if (c.push_token) arr.push({ key: "push", title: "Push" });
  if (c.telegram_id) arr.push({ key: "telegram", title: "Telegram" });
  return arr;
}
function emptyCell(text = "—") {
  return `<span class="empty" title="Не задано">${text}</span>`;
}
function renderContacts() {
  updateFilterCounts();
  const filtered = applyFilter(contactsAfterSearch());
  const total = filtered.length;
  const totalAll = state.contacts.length;

  const pagesCount = Math.max(1, Math.ceil(total / state.contactsPageSize));
  if (state.contactsPage > pagesCount) state.contactsPage = pagesCount;
  const start = (state.contactsPage - 1) * state.contactsPageSize;
  const items = filtered.slice(start, start + state.contactsPageSize);

  const searching = state.search || state.filter;
  $("#result-count").textContent = searching
    ? `Найдено: ${total} из ${totalAll}` : "";

  const selCount = state.selectedContactIds.size;
  $("#bulk-toolbar").style.display = selCount > 0 ? "flex" : "none";
  $("#bulk-count").textContent = selCount;

  if (!items.length) {
    const msg = totalAll === 0
      ? 'Контактов пока нет. Нажмите «+ Добавить контакт» внизу страницы.'
      : (searching
          ? 'Ничего не найдено. Попробуйте изменить запрос или сбросить фильтры.'
          : 'Список пуст.');
    $("#contacts-table").innerHTML = `<div class="empty-state">${msg}</div>`;
  } else {
    $("#contacts-table").innerHTML = items.map(c => {
      const chs = channelsOf(c);
      const chEmojis = chs.length
        ? chs.map(x => channelByKey(x.key).emoji).join("")
        : emptyCell("—");
      const chTitle = chs.length
        ? chs.map(x => x.title).join(", ")
        : "Нет настроенных каналов";
      const selected = state.selectedContactIds.has(c.id);
      return `<div class="contact-row${selected ? ' selected' : ''}">
        <input type="checkbox" class="cb row-select" data-id="${c.id}"
               ${selected ? "checked" : ""}>
        <span>${escapeHtml(c.name)}</span>
        ${c.email ? `<span>${escapeHtml(c.email)}</span>` : emptyCell()}
        ${c.phone ? `<span>${escapeHtml(c.phone)}</span>` : emptyCell()}
        ${c.telegram_id ? `<span>${escapeHtml(c.telegram_id)}</span>` : emptyCell()}
        <span class="channels-cell" title="${escapeHtml(chTitle)}">${chEmojis}</span>
        <span class="actions">
          <button class="btn-icon" data-history="${c.id}"
                  title="Посмотреть историю сообщений">🕘</button>
          <button class="btn-icon danger" data-delete="${c.id}"
                  title="Удалить контакт">🗑</button>
        </span>
      </div>`;
    }).join("");
  }

  const allBox = $("#select-all-page");
  const pageIds = items.map(c => c.id);
  const selectedOnPage = pageIds.filter(id => state.selectedContactIds.has(id)).length;
  allBox.checked = pageIds.length > 0 && selectedOnPage === pageIds.length;
  allBox.indeterminate = selectedOnPage > 0 && selectedOnPage < pageIds.length;
  allBox.disabled = pageIds.length === 0;

  $("#pagination-bar").style.display = total > 0 ? "flex" : "none";
  $("#pagination-info").textContent = total
    ? `Показано ${start + 1}–${Math.min(start + state.contactsPageSize, total)} из ${total}`
    : "";
  $("#page-prev").disabled = state.contactsPage <= 1;
  $("#page-next").disabled = state.contactsPage >= pagesCount;

  const nums = [];
  const addNum = (n) => nums.push(
    `<button class="page-num ${n===state.contactsPage?'on':''}" data-page="${n}">${n}</button>`
  );
  if (pagesCount <= 7) {
    for (let i = 1; i <= pagesCount; i++) addNum(i);
  } else {
    addNum(1);
    if (state.contactsPage > 3) nums.push(`<span class="muted">…</span>`);
    const from = Math.max(2, state.contactsPage - 1);
    const to = Math.min(pagesCount - 1, state.contactsPage + 1);
    for (let i = from; i <= to; i++) addNum(i);
    if (state.contactsPage < pagesCount - 2) nums.push(`<span class="muted">…</span>`);
    addNum(pagesCount);
  }
  $("#page-numbers").innerHTML = nums.join("");

  renderComposer();
}
async function loadContacts() {
  state.contacts = await api("/contacts");
  const ids = new Set(state.contacts.map(c => c.id));
  [...state.selectedContactIds].forEach(id => {
    if (!ids.has(id)) state.selectedContactIds.delete(id);
  });
  renderContacts();
}

$$(".filter-chip").forEach(btn => {
  btn.addEventListener("click", () => {
    const f = btn.dataset.filter;
    state.filter = (state.filter === f) ? "" : f;
    state.contactsPage = 1;
    renderContacts();
  });
});
$("#filter-clear").addEventListener("click", () => {
  state.search = "";
  state.filter = "";
  $("#contact-search").value = "";
  state.contactsPage = 1;
  renderContacts();
});
$("#contact-search").addEventListener("input", (e) => {
  state.search = e.target.value;
  state.contactsPage = 1;
  renderContacts();
});

$("#select-all-page").addEventListener("change", (e) => {
  const filtered = applyFilter(contactsAfterSearch());
  const start = (state.contactsPage - 1) * state.contactsPageSize;
  const ids = filtered.slice(start, start + state.contactsPageSize).map(c => c.id);
  if (e.target.checked) ids.forEach(id => state.selectedContactIds.add(id));
  else ids.forEach(id => state.selectedContactIds.delete(id));
  renderContacts();
});
$("#contacts-table").addEventListener("change", (e) => {
  const cb = e.target.closest(".row-select");
  if (!cb) return;
  const id = Number(cb.dataset.id);
  cb.checked ? state.selectedContactIds.add(id) : state.selectedContactIds.delete(id);
  renderContacts();
});
$("#bulk-clear").addEventListener("click", () => {
  state.selectedContactIds.clear();
  renderContacts();
});
$("#bulk-delete").addEventListener("click", () => {
  const ids = [...state.selectedContactIds];
  if (!ids.length) return;
  confirmDialog(
    "Удаление контактов",
    `Удалить выбранные контакты (${ids.length} шт.) и всю их историю сообщений? ` +
    `Это действие нельзя отменить.`,
    async () => {
      try {
        const r = await api("/contacts/bulk-delete", {
          method: "POST", body: JSON.stringify({ ids }),
        });
        state.selectedContactIds.clear();
        await loadContacts();
        await loadDashboard();
        toast(`Удалено контактов: ${r.deleted}`, "success");
      } catch (e) { toast("Ошибка удаления: " + e.message, "error"); }
    }
  );
});

$("#page-size").addEventListener("change", (e) => {
  state.contactsPageSize = Number(e.target.value);
  state.contactsPage = 1;
  renderContacts();
});
$("#page-prev").addEventListener("click", () => {
  if (state.contactsPage > 1) { state.contactsPage--; renderContacts(); }
});
$("#page-next").addEventListener("click", () => {
  const filtered = applyFilter(contactsAfterSearch());
  const pages = Math.ceil(filtered.length / state.contactsPageSize);
  if (state.contactsPage < pages) { state.contactsPage++; renderContacts(); }
});
$("#page-numbers").addEventListener("click", (e) => {
  const btn = e.target.closest("[data-page]");
  if (!btn) return;
  state.contactsPage = Number(btn.dataset.page);
  renderContacts();
});

/* Модалка добавления контакта — открывается кнопкой в футере */
$("#btn-open-add-contact").addEventListener("click", () => {
  ["#c-name", "#c-email", "#c-phone", "#c-tg"].forEach(s => $(s).value = "");
  $("#c-name-err").classList.remove("show");
  openModal("contact-modal");
});
async function addContact() {
  const name = $("#c-name").value.trim();
  if (!name) { $("#c-name-err").classList.add("show"); return; }
  $("#c-name-err").classList.remove("show");

  await withLoading($("#btn-add-contact"), async () => {
    try {
      await api("/contacts", { method:"POST", body: JSON.stringify({
        name,
        email: $("#c-email").value.trim() || null,
        phone: $("#c-phone").value.trim() || null,
        telegram_id: $("#c-tg").value.trim() || null,
        default_channel: "email",
      })});
      closeModal("contact-modal");
      await loadContacts();
      toast(`Контакт «${name}» добавлен`, "success");
    } catch (e) { toast("Не удалось добавить: " + e.message, "error"); }
  });
}
$("#btn-add-contact").addEventListener("click", addContact);

$("#contacts-table").addEventListener("click", (e) => {
  const hist = e.target.closest("[data-history]");
  if (hist) { openHistory(Number(hist.dataset.history)); return; }
  const del = e.target.closest("[data-delete]");
  if (del) { deleteContact(Number(del.dataset.delete)); }
});
function deleteContact(id) {
  const c = state.contacts.find(x => x.id === id);
  if (!c) return;
  confirmDialog(
    "Удаление контакта",
    `Удалить «${c.name}» и всю его историю сообщений? Это действие нельзя отменить.`,
    async () => {
      try {
        await api(`/contacts/${id}`, { method: "DELETE" });
        state.selectedContacts.delete(id);
        state.selectedContactIds.delete(id);
        await loadContacts();
        await loadDashboard();
        toast(`Контакт «${c.name}» удалён`, "success");
      } catch (e) { toast("Не удалось удалить: " + e.message, "error"); }
    }
  );
}

async function openHistory(id) {
  const contact = state.contacts.find(c => c.id === id);
  $("#history-title").textContent = contact
    ? `История: ${contact.name}` : "История сообщений";
  $("#history-body").innerHTML = `<div class="empty-state">Загрузка…</div>`;
  openModal("history-modal");
  try {
    const items = await api(`/contacts/${id}/messages`);
    if (!items.length) {
      $("#history-body").innerHTML =
        `<div class="empty-state">Сообщений этому контакту пока не отправлялось</div>`;
      return;
    }
    $("#history-body").innerHTML = items.map(m => {
      const ch = channelByKey(m.channel);
      const time = m.created_at
        ? new Date(m.created_at + "Z").toLocaleString("ru-RU") : "";
      return `<div class="msg-row" data-msg-id="${m.id}">
        <span class="msg-ch">${ch.emoji}</span>
        <div>
          <div class="msg-name">${escapeHtml(m.subject||"без темы")}
            <span class="msg-time">· ${time}</span></div>
          <div class="msg-body">${escapeHtml(m.body||"")}${m.error ? " — " + escapeHtml(m.error) : ""}</div>
        </div>
        <span class="msg-time">шаг ${m.step_index + 1}</span>
        <span class="badge ${m.status}" title="${escapeHtml(STATUS_HINT[m.status]||"")}">${STATUS_LABEL[m.status]||m.status}</span>
        <span></span>
      </div>`;
    }).join("");
  } catch (e) {
    $("#history-body").innerHTML =
      `<div class="empty-state">Ошибка: ${escapeHtml(e.message)}</div>`;
  }
}
$("#history-body").addEventListener("click", (e) => {
  const row = e.target.closest("[data-msg-id]");
  if (row) {
    closeModal("history-modal");
    openMessageDetail(Number(row.dataset.msgId));
  }
});

/* ============================================================
   КАСКАДЫ
   ============================================================ */
function renderCascadePreview() {
  const steps = [...document.querySelectorAll(".step-row")].map(row => ({
    channel: row.querySelector(".ch-select").value,
    delay: Number(row.querySelector(".delay-input").value) || 0,
  }));
  const box = $("#cascade-preview");
  if (!steps.length) {
    box.innerHTML = `<div class="cascade-meta">Предпросмотр цепочки</div>
      <div class="empty-state" style="padding:8px;font-size:11px">Добавьте шаги</div>`;
    return;
  }
  const nodes = steps.map(s => {
    const ch = channelByKey(s.channel);
    return `<div class="cascade-node">
      <span style="color:${ch.color};font-size:16px">${ch.emoji}</span>
      <strong>${ch.title}</strong>
      <span style="margin-left:auto;font-size:11px;color:var(--muted)">таймаут ${s.delay}с</span>
    </div>`;
  }).join(`<div class="cascade-arrow">▼</div>`);
  box.innerHTML = `<div class="cascade-meta">Предпросмотр цепочки</div>${nodes}`;
}
function addStepRow(channel = "push", delay = 5) {
  const row = document.createElement("div");
  row.className = "step-row";
  row.innerHTML = `
    <select class="input ch-select" style="max-width:200px">
      ${state.channels.map(c => `<option value="${c.key}" ${c.key===channel?"selected":""}>${c.emoji} ${c.title}</option>`).join("")}
    </select>
    <input class="input delay-input" type="number" min="1" max="300" value="${delay}"
           style="max-width:120px" title="Таймаут ожидания доставки (1–300 сек)">
    <span class="muted">сек. таймаут доставки</span>
    <button class="btn-ghost remove-step" style="margin:0" title="Удалить шаг">×</button>`;
  row.querySelector(".remove-step").addEventListener("click", () => {
    row.remove(); renderCascadePreview();
  });
  row.querySelector(".ch-select").addEventListener("change", renderCascadePreview);
  row.querySelector(".delay-input").addEventListener("input", renderCascadePreview);
  $("#cascade-steps").appendChild(row);
  renderCascadePreview();
}
async function loadCascades() {
  state.cascades = await api("/cascades");
  $("#cascades-list").innerHTML = state.cascades.map(c => `
    <div class="cascade-card">
      <div class="cascade-card-head">
        <div class="int-title">${escapeHtml(c.name)}</div>
        <button class="btn-icon danger" data-cascade-delete="${c.id}"
                title="Удалить каскад">🗑</button>
      </div>
      <div class="cascade-flow">
        ${c.steps.map((s, i) => {
          const ch = channelByKey(s.channel);
          return `<strong>${i+1}.</strong> ${ch.emoji} ${ch.title}` +
                 (s.delay_seconds ? ` → ждать до ${s.delay_seconds} сек.` : "");
        }).join("<br>")}
      </div>
    </div>`).join("") || `<div class="empty-state">Каскадов пока нет</div>`;

  $("#cascades-list").querySelectorAll("[data-cascade-delete]").forEach(btn => {
    btn.addEventListener("click", () => deleteCascade(Number(btn.dataset.cascadeDelete)));
  });
  renderComposer();
}
function deleteCascade(id) {
  const cascade = state.cascades.find(c => c.id === id);
  if (!cascade) return;
  confirmDialog(
    "Удаление каскада",
    `Удалить каскад «${cascade.name}»? Кампании и сообщения, которые его ` +
    `использовали, останутся, но потеряют привязку к каскаду. ` +
    `Это действие нельзя отменить.`,
    async () => {
      try {
        await api(`/cascades/${id}`, { method: "DELETE" });
        await loadCascades();
        toast(`Каскад «${cascade.name}» удалён`, "success");
      } catch (e) { toast("Не удалось удалить: " + e.message, "error"); }
    }
  );
}
async function saveCascade() {
  const name = $("#cascade-name").value.trim();
  const steps = [...document.querySelectorAll(".step-row")].map(row => ({
    channel: row.querySelector(".ch-select").value,
    delay_seconds: Number(row.querySelector(".delay-input").value) || 0,
  }));
  let ok = true;
  if (!name) { toast("Укажите название сценария", "error"); ok = false; }
  if (!steps.length) { $("#err-cascade-form").classList.add("show"); ok = false; }
  else $("#err-cascade-form").classList.remove("show");
  if (!ok) return;
  if (steps.some(s => s.delay_seconds < 1 || s.delay_seconds > 300)) {
    toast("Таймаут должен быть от 1 до 300 секунд", "error"); return;
  }
  await withLoading($("#btn-save-cascade"), async () => {
    try {
      await api("/cascades", { method:"POST", body: JSON.stringify({ name, steps }) });
      $("#cascade-name").value = "";
      $("#cascade-steps").innerHTML = "";
      renderCascadePreview();
      await loadCascades();
      toast(`Каскад «${name}» сохранён`, "success");
    } catch (e) { toast("Не удалось сохранить: " + e.message, "error"); }
  });
}

/* ============================================================
   ИНТЕГРАЦИИ
   ============================================================ */
const INT_STATUS_LABEL = {
  connected: "● Активно",
  setup_required: "○ Не подключено",
  auth_error: "✕ Ошибка аутентификации",
  needs_refresh: "⟳ Требуется обновление ключей",
  rate_limited: "⏸ Превышен лимит запросов",
};
async function loadIntegrations() {
  const items = await api("/integrations");
  $("#integrations-grid").innerHTML = items.map(i => {
    const connected = i.status === "connected";
    const btnHint = connected
      ? "Отключение деактивирует канал, но не удалит ключи"
      : "Откроется форма ввода API-ключей";
    const errorBlock = i.errors && i.errors.length
      ? `<div class="int-errors">
          ${i.errors.map(e => `<div>${new Date(e.created_at + "Z").toLocaleString("ru-RU")} — ${escapeHtml(e.message)}</div>`).join("")}
        </div>` : "";
    return `<div class="int-card">
      <div class="int-title">${escapeHtml(i.title)}</div>
      <div class="int-status ${i.status}">${INT_STATUS_LABEL[i.status] || i.status}</div>
      <div class="int-reason">${escapeHtml(i.reason)}</div>
      ${errorBlock}
      <button class="btn-ghost" data-provider="${i.provider}" data-connected="${connected}"
              title="${btnHint}">${connected ? "Отключить" : "Подключить"}</button>
    </div>`;
  }).join("");
  $("#integrations-grid").querySelectorAll("button[data-provider]").forEach(btn => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.provider;
      try {
        if (btn.dataset.connected === "true") {
          await api(`/integrations/${provider}/disconnect`, { method:"POST" });
          toast("Интеграция отключена (ключи сохранены)", "info");
        } else {
          const key = prompt("Введите API-ключ (в демо подойдёт любой):", "demo-key");
          if (!key) return;
          await api(`/integrations/${provider}/connect`, {
            method:"POST", body: JSON.stringify({ config: { api_key: key } }),
          });
          toast("Интеграция подключена", "success");
        }
        loadIntegrations();
      } catch (e) { toast("Ошибка: " + e.message, "error"); }
    });
  });
}

/* ---------- WebSocket ---------- */
function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onopen = () => { $("#ws-status").className = "dot dot-on"; };
  ws.onclose = () => {
    $("#ws-status").className = "dot dot-off";
    setTimeout(connectWs, 2000);
  };
  ws.onmessage = () => {
    if ($("#sec-dashboard").classList.contains("active")) loadDashboard();
  };
}

/* ---------- Инициализация ---------- */
async function boot() {
  applyTheme(localStorage.getItem("omni-theme") || "dark");
  $("#theme-toggle").addEventListener("click", toggleTheme);

  state.channels = await api("/channels");
  await Promise.all([loadContacts(), loadCascades(), loadIntegrations()]);
  await loadDashboard();

  $("#btn-send").addEventListener("click", sendMessage);
  $("#btn-add-step").addEventListener("click", () => addStepRow());
  $("#btn-save-cascade").addEventListener("click", saveCascade);

  const debounce = () => {
    clearTimeout(window.__pv);
    window.__pv = setTimeout(updatePreview, 200);
  };
  $("#in-body").addEventListener("input", debounce);
  $("#in-subject").addEventListener("input", debounce);

  connectWs();
  setMode("direct");
  renderCascadePreview();
  updatePreview();
  setInterval(() => {
    if ($("#sec-dashboard").classList.contains("active")) loadDashboard();
  }, 5000);
}
boot();
</script>
</body>
</html>
"""


# ============================================================
# FASTAPI
# ============================================================
async def seed_demo_data() -> None:
    async with SessionLocal() as db:
        if await db.scalar(select(Contact).limit(1)):
            return
        db.add_all([
            Contact(name="Иван Иванов", email="ivan@example.com", phone="+79001112233",
                    telegram_id="100200300", push_token="fcm-ivan",
                    default_channel="telegram"),
            Contact(name="Пётр Петров", email="petr@example.com", phone="+79004445566",
                    default_channel="email"),
            Contact(name="Анна Смирнова", email="anna@example.com", phone="+79007778899",
                    telegram_id="400500600", push_token="fcm-anna",
                    default_channel="push"),
            Contact(name="Олег Кузнецов", phone="+79001234567", default_channel="sms"),
        ])
        db.add_all([
            Integration(provider="mailgun", title="Mailgun", channel="email",
                        status="connected", config={"api_key": "demo"}),
            Integration(provider="twilio", title="Twilio", channel="sms",
                        status="auth_error", config={"api_key": "expired"}),
            Integration(provider="firebase", title="Firebase", channel="push"),
            Integration(provider="telegram", title="Telegram Bot", channel="telegram"),
        ])
        db.add(Cascade(
            name="Push → Telegram → SMS",
            steps=[
                {"channel": "push", "delay_seconds": 5},
                {"channel": "telegram", "delay_seconds": 10},
                {"channel": "sms", "delay_seconds": 30},
            ],
        ))
        db.add_all([
            IntegrationErrorLog(provider="twilio",
                message="Ошибка API: 401 Unauthorized — ключ отклонён"),
            IntegrationErrorLog(provider="twilio",
                message="Ошибка API: 429 Too Many Requests"),
        ])
        await db.commit()
        log.info("Демо-данные загружены в %s", DB_PATH)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_demo_data()
    yield


app = FastAPI(title="Omni Messenger", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api")


@app.get("/", response_class=HTMLResponse)
async def index():
    return INDEX_HTML


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)


# ============================================================
# DESKTOP
# ============================================================
def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _run_server(port: int) -> None:
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _run_desktop(port: int) -> None:
    threading.Thread(target=_run_server, args=(port,), daemon=True).start()
    if not _wait_for_port(port):
        print("Ошибка: сервер не запустился", file=sys.stderr)
        sys.exit(1)
    import webview
    url = f"http://127.0.0.1:{port}"
    log.info("Открываю окно: %s", url)
    webview.create_window("Omni Messenger", url, width=1440, height=920,
                          min_size=(1100, 720), background_color="#0D1117",
                          text_select=True)
    webview.start()


def _run_web(port: int) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{port}"
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"Открываю {url} в браузере")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    requested = int(os.environ.get("PORT", "0"))
    port = requested or _find_free_port()
    if "--web" in sys.argv:
        _run_web(port)
    else:
        try:
            import webview  # noqa: F401
        except ImportError:
            print("pywebview не установлен. Установите: pip install pywebview\n"
                  "Или запустите: python main.py --web", file=sys.stderr)
            sys.exit(1)
        _run_desktop(port)
