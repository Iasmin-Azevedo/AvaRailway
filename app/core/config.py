from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AVA MJ Backend"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MOODLE_URL: str
    MOODLE_TOKEN: str

    class Config:
        env_file = ".env"

settings = Settings()