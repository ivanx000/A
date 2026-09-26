from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./pipeline.db"

    # LinkedIn watch (--watch-linkedin) — overridable per-run with --keywords/--location
    linkedin_keywords: str = "Software Engineer Intern"
    linkedin_location: str = "Canada"

    # Filtering — software + AI/ML roles. Matched on word boundaries, so
    # "software" is needed to catch "Software Engineering/Development Intern".
    # Tech-stack terms catch career pages that name the team rather than the
    # role ("Firefox Graphics team" + a blurb mentioning CSS).
    target_keywords: list[str] = [
        "software", "developer", "programmer", "swe",
        "ai", "ml", "machine learning", "deep learning", "llm", "nlp",
        "artificial intelligence", "generative ai", "genai", "computer vision",
        "data science", "data scientist", "data engineer",
        "full stack", "fullstack", "full-stack",
        "backend", "back-end", "back end",
        "frontend", "front-end", "front end",
        "cloud", "devops", "saas", "web", "browser", "browsers", "api", "apis",
        "ios", "android", "mobile developer", "linux", "macos",
        "python", "java", "javascript", "typescript", "rust", "react", "django", "css",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
