"""Request bodies of the payments API (module 21). Amounts are integers of minor units; currencies ISO 4217 codes."""
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, StringConstraints

from . import money

Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(max_length=2000)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]
Currency = Annotated[str, AfterValidator(money.currency)]
Amount = Annotated[int, Field(ge=0, le=money.MAX_AMOUNT)]
Positive = Annotated[int, Field(ge=1, le=money.MAX_AMOUNT)]
Quantity = Annotated[int, Field(ge=1, le=100000)]
Basis = Annotated[int, Field(ge=0, le=10000)]
Code = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9_-]{2,40}$")]
Url = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000, pattern=r"^https?://\S+$")]


class Connect(BaseModel):
    provider: Literal["stripe", "fake"] = "stripe"


class SettingsPatch(BaseModel):
    default_currency: Currency | None = None
    invoice_prefix: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20,
                                                     pattern=r"^[A-Za-z0-9/_-]*$")] | None = None
    invoice_due_days: Annotated[int, Field(ge=0, le=365)] | None = None
    retry_days: Annotated[list[Annotated[int, Field(ge=1, le=60)]], Field(max_length=8)] | None = None
    after_retries: Literal["cancel", "unpaid"] | None = None
    business_name: Annotated[str, StringConstraints(max_length=200)] | None = None
    business_details: Annotated[str, StringConstraints(max_length=1000)] | None = None
    invoice_footer: Annotated[str, StringConstraints(max_length=1000)] | None = None


class TaxIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    percentage_bp: Basis
    inclusive: bool = False
    region: Short = ""


class TaxPatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    region: Short | None = None
    active: bool | None = None


class TierIn(BaseModel):
    up_to: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    unit_amount: Amount = 0
    flat_amount: Amount = 0


class PriceIn(BaseModel):
    currency: Currency
    type: Literal["one_time", "recurring"] = "one_time"
    scheme: Literal["fixed", "tiered"] = "fixed"
    unit_amount: Amount | None = None
    tiers: Annotated[list[TierIn], Field(max_length=20)] = []
    tiers_mode: Literal["graduated", "volume"] | None = None
    interval: Literal["day", "week", "month", "year"] | None = None
    interval_count: Annotated[int, Field(ge=1, le=365)] = 1
    trial_days: Annotated[int, Field(ge=0, le=730)] = 0
    tax_rate_id: uuid.UUID | None = None
    nickname: Short = ""


class PricePatch(BaseModel):
    nickname: Short | None = None
    active: bool | None = None


class ProductIn(BaseModel):
    name: Name
    description: Text = ""
    kind: Literal["service", "physical", "digital"] = "service"
    prices: Annotated[list[PriceIn], Field(max_length=20)] = []


class ProductPatch(BaseModel):
    name: Name | None = None
    description: Text | None = None
    kind: Literal["service", "physical", "digital"] | None = None
    active: bool | None = None


class CouponIn(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    code: Code
    percent_off_bp: Annotated[int, Field(ge=1, le=10000)] | None = None
    amount_off: Positive | None = None
    currency: Currency | None = None
    duration: Literal["once", "repeating", "forever"] = "once"
    duration_months: Annotated[int, Field(ge=1, le=120)] | None = None
    max_redemptions: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    once_per_contact: bool = False
    price_ids: Annotated[list[uuid.UUID], Field(max_length=100)] = []
    starts_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None


class CouponPatch(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = None
    max_redemptions: Annotated[int, Field(ge=1, le=10_000_000)] | None = None
    expires_at: AwareDatetime | None = None
    active: bool | None = None


class LinkItem(BaseModel):
    price_id: uuid.UUID
    quantity: Quantity = 1
    adjustable: bool = False
    min: Quantity = 1
    max: Quantity = 99


class LinkIn(BaseModel):
    name: Name
    items: Annotated[list[LinkItem], Field(min_length=1, max_length=10)]
    allow_coupons: bool = False
    collect_phone: bool = False
    success_message: Annotated[str, StringConstraints(max_length=1000)] = ""
    redirect_url: Url | None = None


class LinkPatch(BaseModel):
    name: Name | None = None
    items: Annotated[list[LinkItem], Field(min_length=1, max_length=10)] | None = None
    allow_coupons: bool | None = None
    collect_phone: bool | None = None
    success_message: Annotated[str, StringConstraints(max_length=1000)] | None = None
    redirect_url: Url | None = None
    active: bool | None = None


class LineIn(BaseModel):
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None
    price_id: uuid.UUID | None = None
    quantity: Quantity = 1
    unit_amount: Annotated[int, Field(ge=0, le=money.MAX_AMOUNT)] | None = None
    tax_rate_id: uuid.UUID | None = None


class InvoiceIn(BaseModel):
    contact_id: uuid.UUID
    currency: Currency | None = None  # default: the workspace's
    lines: Annotated[list[LineIn], Field(max_length=100)] = []
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    due_at: AwareDatetime | None = None
    memo: Text = ""
    footer: Annotated[str, StringConstraints(max_length=1000)] = ""


class InvoicePatch(BaseModel):
    contact_id: uuid.UUID | None = None
    currency: Currency | None = None
    lines: Annotated[list[LineIn], Field(max_length=100)] | None = None
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    due_at: AwareDatetime | None = None
    memo: Text | None = None
    footer: Annotated[str, StringConstraints(max_length=1000)] | None = None


class ManualPayment(BaseModel):
    amount: Positive
    method: Literal["cash", "check", "bank_transfer", "other"] = "cash"
    note: Annotated[str, StringConstraints(max_length=500)] = ""


class Void(BaseModel):
    reason: Annotated[str, StringConstraints(max_length=200)] | None = None


class SubscriptionIn(BaseModel):
    contact_id: uuid.UUID
    price_id: uuid.UUID
    quantity: Quantity = 1
    coupon_code: Annotated[str, StringConstraints(strip_whitespace=True, max_length=40)] | None = None
    trial_days: Annotated[int, Field(ge=0, le=730)] | None = None  # default: the price's
    collection: Literal["charge_automatically", "send_invoice"] = "charge_automatically"


class SubscriptionPatch(BaseModel):
    price_id: uuid.UUID | None = None
    quantity: Quantity | None = None
    prorate: bool = True


class CancelIn(BaseModel):
    at_period_end: bool = True
    reason: Annotated[str, StringConstraints(max_length=500)] | None = None


class RefundIn(BaseModel):
    amount: Positive | None = None  # default: everything left
    reason: Literal["duplicate", "fraudulent", "requested_by_customer"] | None = None
    note: Annotated[str, StringConstraints(max_length=500)] = ""
