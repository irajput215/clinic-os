import warnings
from typing import Literal, Self

from pydantic import (
    EmailStr,
    Field,
    HttpUrl,
    PostgresDsn,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    SECRET_KEY: str
    # Control 1 (`docs/reference/build-contract.md` §6): 15-minute access tokens.
    # `docs/features/02-authentication/01-requirements.md` OPEN-2 records the source conflict (10
    # minutes in doc 06 §3, 15 minutes in doc 02 §1 and doc 03 §4); 15 is the value the build
    # contract states and the one this repository adopts.
    #
    # Until refresh-token rotation lands, this lifetime *is* the whole session: feature 02 specifies
    # rotation and revocation (R4–R7) but they are blocked by D-003, so nothing extends a session
    # past this token. The 8-day value this replaced was the template's, not a decision. The key is
    # deliberately absent from `.env.example`; a deployment overrides it by setting it, and the
    # default carries the control.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    # The origin emailed links (password reset) point at. The backend serves the app at `/`, so
    # locally that is the backend itself (`fastapi dev`, and compose.override.yml, on :8000).
    FRONTEND_HOST: str = "http://localhost:8000"
    FASTAPI_ENV: Literal["development"] | None = None

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None
    DATABASE_URL: PostgresDsn
    # Migrations need an owning role; the application must run least privilege, and one URL cannot
    # be both. Optional: when unset, Alembic falls back to DATABASE_URL and nothing changes. The
    # deployment sets this, out of band, when the migration role is switched on.
    MIGRATION_DATABASE_URL: PostgresDsn | None = None

    @field_validator("DATABASE_URL", "MIGRATION_DATABASE_URL", mode="before")
    @classmethod
    def _use_psycopg_driver(cls, value: str | PostgresDsn | None) -> str | None:
        if value is None:
            return None
        database_url = str(value)
        for scheme in ("postgres://", "postgresql://"):
            if database_url.startswith(scheme):
                return database_url.replace(scheme, "postgresql+psycopg://", 1)
        return database_url

    @model_validator(mode="after")
    def _default_migration_url(self) -> Self:
        # Unset means "same as the application URL", which is exactly the previous behaviour.
        if self.MIGRATION_DATABASE_URL is None:
            self.MIGRATION_DATABASE_URL = self.DATABASE_URL
        return self

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48
    # How long a staff invitation link stays valid (`03-users-and-roles` R10: "Invitations expire if
    # not accepted inside the configured window"). The design does not fix the window; 72 hours lets
    # an invitation sent on a Friday be accepted on the Monday.
    STAFF_INVITATION_EXPIRE_HOURS: int = Field(default=72, ge=1, le=24 * 14)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    # The demo organisation is MVP seed data, not something a deployment should
    # create implicitly. `initial_data.py` seeds it only when this is true, so a
    # real environment must opt in.
    SEED_DEMO_TENANT: bool = False

    # Self-registration at POST /users/signup. Open by default because a signup now
    # registers an organisation (`clinic_name`), so a new account can only ever reach
    # the tenant it created — see docs/reference/business-flow.md step ①. A deployment
    # that would rather provision every account by hand sets this false.
    USERS_OPEN_REGISTRATION: bool = True

    # Sliding-window rate limiting on the abuse-prone unauthenticated endpoints
    # (login, password recovery). Tests clear the window between cases.
    RATE_LIMIT_ENABLED: bool = True

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.FASTAPI_ENV == "development":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        for host in self.DATABASE_URL.hosts():
            self._check_default_secret("DATABASE_URL password", host["password"])
        migration_url = self.MIGRATION_DATABASE_URL or self.DATABASE_URL
        if migration_url != self.DATABASE_URL:
            for host in migration_url.hosts():
                self._check_default_secret(
                    "MIGRATION_DATABASE_URL password", host["password"]
                )
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore # ty: ignore[unused-ignore-comment]
