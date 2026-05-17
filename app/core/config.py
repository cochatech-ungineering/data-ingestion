from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "data-ingestion"
    event_chunk_size: int = 500
    publish_events: bool = True
    archive_published_events: bool = True
    events_output_dir: str = "events/published"

    aws_region: str = "us-east-1"
    aws_profile: str | None = None
    aws_endpoint_url: str | None = None

    sns_topic_arn: str = ""
    sns_topic_name: str = "cashback-ingestion"

    s3_bucket: str = "cochatech-data-ingestion-raw-545349726305"

    database_url: str = ""
    database_ssl_ca: str = "infrastructure/rds-ca-global.pem"
    database_pool_min_size: int = 1
    database_pool_max_size: int = 10


settings = Settings()
