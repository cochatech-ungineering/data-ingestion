from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "data-ingestion"
    event_chunk_size: int = 500
    publish_events: bool = True
    archive_published_events: bool = True
    events_output_dir: str = "events/published"

    # AWS SNS (equivalente al exchange topic cashback.ingestion)
    aws_region: str = "us-east-1"
    aws_profile: str | None = None  # p. ej. cochatech-dev (aws login / ~/.aws/credentials)
    aws_endpoint_url: str | None = None  # p. ej. http://localhost:4566 para LocalStack
    sns_topic_arn: str = ""
    sns_topic_name: str = "cashback-ingestion"

    database_url: str = "postgresql://ingestion:ingestion@localhost:5433/ingestion"
    database_pool_min_size: int = 1
    database_pool_max_size: int = 10

    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "ingestion-raw"
    minio_secure: bool = False
    minio_region: str | None = None


settings = Settings()
