from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int

    LANGFUSE_SECRET_KEY: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_API_HOST: str

    JUDGE_MODEL: str = "openai/gpt-oss-safeguard-20b"

    API_BASE_URL: str
    API_KEY: str

    SCRAPE_HOURS_WINDOW: int = 1

    is_develop_mode: bool = False

    @property
    def database_url(self):
        return f'postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def langfuse_auth(self):
        return (self.LANGFUSE_PUBLIC_KEY, self.LANGFUSE_SECRET_KEY)


settings = Settings()