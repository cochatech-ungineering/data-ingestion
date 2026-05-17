from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "data-ingestion"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    rabbitmq_exchange: str = "cashback.ingestion"
    event_chunk_size: int = 500
    publish_events: bool = True
    archive_published_events: bool = True
    events_output_dir: str = "events/published"


settings = Settings()
