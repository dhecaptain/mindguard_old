from pydantic import BaseModel, Field, field_validator
from typing import Optional


class TextAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)

    @field_validator("text")
    @classmethod
    def text_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("text must not be blank")
        return v


class TextAnalysisResponse(BaseModel):
    prob: float
    latency_ms: float
    analytics: dict
    risk_tier: str = "low"
    alert_eligible: bool = False
    crisis_escalation_eligible: bool = False


class PlatformRequest(BaseModel):
    username: str = ""
    handle: str = ""
    identifier: str = ""
    instance: str = Field(default="mastodon.social", max_length=253)
    password: str = ""
    client_id: str = ""
    client_secret: str = ""
    channel_url: str = ""
    video_url: str = ""
    profile_url: str = ""
    api_key: str = ""
    months: int = Field(default=3, ge=1, le=6)
    min_risk: float = Field(default=0.0, ge=0.0, le=1.0)
    n_show: int = Field(default=20, gt=0, le=500)
    transcribe_videos: bool = True
    transcript_limit: int = Field(default=3, ge=0, le=3)


class LoginRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1)
    recaptcha_token: Optional[str] = None


class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=8, description="Minimum 8 characters")
    role: str = "student"
    dob: Optional[str] = None
    parent_email: Optional[str] = None
    referred_by: Optional[str] = None
    recaptcha_token: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Minimum 8 characters")


class UserResponse(BaseModel):
    email: str
    name: str
    role: str
    role_type: str
    referral_code: str
    terms_accepted: bool = False


# ── Group schemas ──────────────────────────────────────────────────────────────


class CreateGroupRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    member_ids: list[str] = Field(
        default_factory=list, description="Initial members to add"
    )


class UpdateGroupRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)


class AddMemberRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    role: str = Field(default="member", pattern="^(admin|member)$")


class GroupMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class GroupMemberResponse(BaseModel):
    id: str
    user_id: str
    name: str
    email: str
    role: str
    joined_at: str


class GroupResponse(BaseModel):
    id: str
    name: str
    description: str
    avatar_url: str
    created_by: str
    is_active: bool
    member_count: int
    created_at: str
    updated_at: str


class GroupDetailResponse(BaseModel):
    id: str
    name: str
    description: str
    avatar_url: str
    created_by: str
    is_active: bool
    members: list[GroupMemberResponse]
    created_at: str
    updated_at: str


class GroupMessageResponse(BaseModel):
    id: str
    group_id: str
    sender_id: str
    sender_name: str
    message: str
    created_at: str


# ── Notification preference schemas ────────────────────────────────────────────

NOTIFICATION_TYPES = {
    "message",
    "group_message",
    "alert",
    "referral",
    "broadcast",
    "consent",
    "approval",
    "system",
}


class NotificationPreferenceResponse(BaseModel):
    type: str
    enabled: bool
    muted_groups: list[str]


class UpdateNotificationPreferenceRequest(BaseModel):
    enabled: bool | None = None
    muted_groups: list[str] | None = None


class MuteGroupRequest(BaseModel):
    group_id: str = Field(..., min_length=1)
    muted: bool


# ── Consent & roster schemas (Delivery Brief §3) — M1 ─────────────────────────

INSTITUTION_ORGANISATION_TYPES = {"k12", "university", "clinic", "research", "other"}
DEMO_REQUEST_STATUSES = {
    "new",
    "contacted",
    "qualified",
    "demo_scheduled",
    "institution_provisioning",
    "onboarding",
    "closed_won",
    "closed_lost",
}


class InstitutionConsentSettings(BaseModel):
    minor_age_threshold: int = Field(default=18, ge=13, le=21)
    consent_template_id: Optional[str] = None
    consent_reminder_days: list[int] = Field(default_factory=lambda: [3, 7])
    consent_expiry_days: int = Field(default=30, ge=1, le=365)


class StudentResponse(BaseModel):
    id: str
    institution_id: Optional[str] = None
    student_id_hash: str
    first_name: str = ""
    email: str = ""
    date_of_birth: Optional[str] = None
    is_minor: bool
    parent_email: str = ""
    parent_first_name: str = ""
    grade_level: Optional[str] = None
    current_consent_id: Optional[str] = None
    created_at: str
    deleted_at: Optional[str] = None


class ConsentTemplateResponse(BaseModel):
    id: str
    institution_id: Optional[str] = None
    version: str
    language: str
    is_active: bool
    created_at: str
    updated_at: str


class ConsentEventResponse(BaseModel):
    id: str
    consent_id: str
    event_type: str
    actor_type: str
    actor_id: Optional[str] = None
    metadata: dict = {}
    created_at: str


class DemoRequestCreate(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=255)
    work_email: str = Field(..., min_length=3, max_length=255)
    organisation: str = Field(..., min_length=1, max_length=255)
    organisation_type: str = Field(
        default="other", pattern="^(k12|university|company|clinic|research|other)$"
    )
    role_title: Optional[str] = Field(default=None, max_length=255)
    country: Optional[str] = Field(default=None, max_length=64)
    student_count_range: Optional[str] = Field(default=None, max_length=32)
    employee_population_range: Optional[str] = Field(default=None, max_length=32)
    message: Optional[str] = Field(default=None, max_length=5000)
    heard_about_us: Optional[str] = Field(default=None, max_length=64)
    consent_to_contact: bool = True
    # Anti-spam (Brief §5.5/§13.2): invisible honeypot + reCAPTCHA v3 token.
    website: Optional[str] = Field(default=None, max_length=512)
    recaptcha_token: Optional[str] = Field(default=None, max_length=8192)


class DemoRequestResponse(BaseModel):
    id: str
    full_name: str
    work_email: str
    organisation: str
    organisation_type: str
    role_title: Optional[str] = None
    country: Optional[str] = None
    student_count_range: Optional[str] = None
    employee_population_range: Optional[str] = None
    message: Optional[str] = None
    heard_about_us: Optional[str] = None
    status: str
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class DemoRequestUpdate(BaseModel):
    status: Optional[str] = Field(
        default=None,
        pattern="^(new|contacted|qualified|demo_scheduled|institution_provisioning|onboarding|closed_won|closed_lost)$",
    )
    assigned_to: Optional[str] = None
    notes: Optional[str] = None
    meeting_at: Optional[str] = Field(default=None, max_length=64)
    meeting_url: Optional[str] = Field(default=None, max_length=2048)


class EmailEventResponse(BaseModel):
    id: str
    related_type: str
    related_id: Optional[str] = None
    event: str
    esp_message_id: Optional[str] = None
    recipient_email: Optional[str] = None
    metadata: dict = {}
    created_at: str
