"""SQLAlchemy ORM models for ZLP License Authority"""
from datetime import datetime
from typing import Optional
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, Float, JSON, Index
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
import uuid


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String)
    slug: Mapped[str] = mapped_column(String, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    license_keys: Mapped[list["LicenseKey"]] = relationship("LicenseKey", back_populates="product")
    plans: Mapped[list["ProductPlan"]] = relationship("ProductPlan", back_populates="product", order_by="ProductPlan.sort_order")


class ProductPlan(Base):
    __tablename__ = "product_plans"
    __table_args__ = (
        Index("idx_product_plans_product_id", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    default_seats: Mapped[int] = mapped_column(Integer, default=1)
    max_seats: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    features: Mapped[list] = mapped_column(JSON, default=list)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    price_cents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # per 30-day period
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    product: Mapped["Product"] = relationship("Product", back_populates="plans")


class LicenseKey(Base):
    __tablename__ = "license_keys"
    __table_args__ = (
        Index("idx_license_keys_key", "key"),
        Index("idx_license_keys_product", "product_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String, unique=True)
    plan: Mapped[str] = mapped_column(String)  # starter | professional | enterprise
    seats: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | suspended | revoked
    customer_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    renewal_period_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)  # 30 | 90 | 180
    customer_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    product: Mapped[Product] = relationship("Product", back_populates="license_keys")
    installs: Mapped[list["Install"]] = relationship("Install", back_populates="license_key")
    billing_subscriptions: Mapped[list["BillingSubscription"]] = relationship("BillingSubscription", back_populates="license_key")
    invoices: Mapped[list["Invoice"]] = relationship("Invoice", back_populates="license_key", order_by="Invoice.created_at.desc()")


class Install(Base):
    __tablename__ = "installs"
    __table_args__ = (
        Index("idx_installs_key_id", "key_id"),
        Index("idx_installs_install_id", "install_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("license_keys.id", ondelete="CASCADE"))
    install_id: Mapped[str] = mapped_column(String, unique=True)
    domain: Mapped[str] = mapped_column(String)
    fingerprint: Mapped[str] = mapped_column(String)
    machine_id: Mapped[str] = mapped_column(String)
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String, default="active")  # active | blocked | anomalous
    registered_ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    shared_secret_encrypted: Mapped[str] = mapped_column(String)  # AES-256-GCM encrypted base64
    shared_secret_nonce: Mapped[str] = mapped_column(String)  # Nonce for decryption

    license_key: Mapped[LicenseKey] = relationship("LicenseKey", back_populates="installs")


class HeartbeatLog(Base):
    __tablename__ = "heartbeat_log"
    __table_args__ = (
        Index("idx_heartbeat_install_id", "install_id"),
        Index("idx_heartbeat_timestamp", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    install_id: Mapped[str] = mapped_column(String)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    payload_hash: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    response_status: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source_ip: Mapped[Optional[str]] = mapped_column(String, nullable=True)


class AnomalyEvent(Base):
    __tablename__ = "anomaly_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    install_id: Mapped[str] = mapped_column(String)
    score: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(String)
    triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class BillingSubscription(Base):
    __tablename__ = "billing_subscriptions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    license_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("license_keys.id", ondelete="CASCADE"), nullable=False)
    gateway: Mapped[str] = mapped_column(String, nullable=False)
    gateway_ref: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    overdue_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_payment_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    license_key: Mapped["LicenseKey"] = relationship("LicenseKey", back_populates="billing_subscriptions")


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("idx_invoices_license_key_id", "license_key_id"),
        Index("idx_invoices_status", "status"),
        Index("idx_invoices_due_date", "due_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    license_key_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("license_keys.id", ondelete="CASCADE"))
    invoice_number: Mapped[str] = mapped_column(String, unique=True)
    period_days: Mapped[int] = mapped_column(Integer)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    amount_cents: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | sent | paid | void
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    paid_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    license_key: Mapped["LicenseKey"] = relationship("LicenseKey", back_populates="invoices")


class AuditTrail(Base):
    __tablename__ = "audit_trail"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    target_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
