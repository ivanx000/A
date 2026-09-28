from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./pipeline.db"

    # LinkedIn watch (--watch-linkedin) — overridable per-run with --keywords/--location
    linkedin_keywords: str = "Software Engineer Intern"
    linkedin_location: str = "Canada"

    # Company career sites (--watch-companies) — display name → careers-board URL.
    # Greenhouse/Lever/Ashby/Workday board URLs are polled via their JSON APIs; any other URL is
    # fetched and treated as a SuccessFactors site or a hand-made list of openings (see
    # app/ingestion/company_boards.py).
    # Override in .env as JSON: COMPANY_BOARDS={"Cohere": "https://jobs.ashbyhq.com/cohere"}
    company_boards: dict[str, str] = {
        "Cohere": "https://jobs.ashbyhq.com/cohere",
        "Wealthsimple": "https://jobs.ashbyhq.com/wealthsimple",
        "1Password": "https://jobs.ashbyhq.com/1password",
        "Ada": "https://job-boards.greenhouse.io/ada18",
        "RBC": "https://rbc.wd3.myworkdayjobs.com/en-US/RBCGLOBAL1",
        "Celestica": "https://careers.celestica.com/",
        "Mozilla Firefox": "https://soloist.ai/firefox2027internships",
        "Objectway": "https://jobs.eu.lever.co/objectway",
    }

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
        "site reliability", "sre", "firmware", "embedded", "automation", "qa",
        "cyber", "cybersecurity", "security", "applied scientist", "research scientist",
        "quantitative", "quant", "analytics", "ux", "ui",
        "développement", "développeur", "logiciel", "informatique", "données",
    ]

    # Broad tech terms — checked against the title only (descriptions use them
    # incidentally) so titles like "Engineer Intern", "IT Co-op", "Student,
    # Emerging Technologies" or "Data Engineering Intern" aren't rejected.
    # Skipped when the title names a non-software engineering discipline.
    broad_title_keywords: list[str] = [
        "engineer", "engineering", "development", "technology", "technologies",
        "tech", "technical", "it", "data", "digital", "systems", "platform",
        "infrastructure", "research", "scientist", "ingénierie", "technologique",
    ]
    non_software_disciplines: list[str] = [
        "mechanical", "civil", "chemical", "structural", "electrical", "power system",
        "building", "process", "manufacturing", "mining", "geotechnical",
        "environmental", "industrial", "nuclear", "propulsion", "materials",
        "aerospace", "biomedical", "construction", "facilities", "hvac",
        "combustion", "mechatronic", "mechatronics", "thermal",
    ]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
