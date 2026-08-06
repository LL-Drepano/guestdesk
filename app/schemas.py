from pydantic import BaseModel, EmailStr, Field


class IncomingMessage(BaseModel):
    sender: EmailStr
    body: str = Field(min_length=1, max_length=50_000)
    subject: str | None = Field(default=None, max_length=500)
    provider_message_id: str | None = Field(default=None, max_length=255)


class IngestResult(BaseModel):
    message_id: int
    job_id: int
    status: str