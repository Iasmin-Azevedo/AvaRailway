from pydantic import field_validator # Adicione este import
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "AVA MJ Backend"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    MOODLE_URL: str
    MOODLE_TOKEN: str
    H5P_CONTENT_DIR: str = "app/templates/static/h5p"

    # Esse bloco garante que o SQLAlchemy use o PyMySQL automaticamente
    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def fix_database_url(cls, v: str) -> str:
        if v and v.startswith("mysql://"):
            return v.replace("mysql://", "mysql+pymysql://", 1)
        return v

    class Config:
        env_file = ".env"
        extra = "ignore" # Importante para o Railway não dar erro com variáveis extras

settings = Settings()