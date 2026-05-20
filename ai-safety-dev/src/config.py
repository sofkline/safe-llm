from pydantic_settings import BaseSettings, SettingsConfigDict
import os
from dotenv import load_dotenv
load_dotenv()

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(__file__), '..', '.env'),
        env_file_encoding='utf-8',
        extra='ignore'
    )

    DB_NAME: str
    DB_USER: str
    DB_PASSWORD: str
    DB_HOST: str
    DB_PORT: int

    LANGFUSE_SECRET_KEY: str
    LANGFUSE_PUBLIC_KEY: str
    LANGFUSE_API_HOST: str

    JUDGE_MODEL: str = "ollama/gemma3:12b" #"openrouter/nvidia/nemotron-3-super-120b-a12b:free"
    BEHAVIORAL_LLM_MODEL: str = "ollama/gemma3:12b" #"openrouter/nvidia/nemotron-3-super-120b-a12b:free"

    API_BASE_URL: str
    API_KEY: str

    SCRAPE_HOURS_WINDOW: int = 1

    is_develop_mode: bool = True

    @property
    def database_url(self):
        return f'postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}'

    @property
    def langfuse_auth(self):
        return (self.LANGFUSE_PUBLIC_KEY, self.LANGFUSE_SECRET_KEY)


settings = Settings()