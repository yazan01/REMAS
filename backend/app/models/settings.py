"""Platform settings an administrator can change without a code change (FR-31).

The BRD's security NFR asks for *secure secrets management*, so a value marked
secret never lands in the table as plain text: it is sealed with the same
AES-256-GCM envelope the evidence files use, under the reserved tenant scope
``platform``. What comes back to the administration portal is a hint — the last
four characters — never the key itself.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, LargeBinary, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDMixin

#: Key scope used to derive the encryption key for platform-wide secrets. It is
#: deliberately not a real organisation id, so a tenant key can never open it.
PLATFORM_SCOPE = "platform"


class PlatformSetting(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "platform_settings"

    key: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    value: Mapped[str | None] = mapped_column(Text, default=None)
    #: Sealed bytes for secret settings; `value` stays NULL for those.
    secret: Mapped[bytes | None] = mapped_column(LargeBinary, default=None)
    #: Enough to recognise which key is installed, not enough to use it.
    hint: Mapped[str | None] = mapped_column(String(32), default=None)
    updated_by_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), default=None
    )
