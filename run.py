import os

from dotenv import load_dotenv

# Load ``.env`` before ``from app import …`` so ``app.config`` sees POSTGRES_* / DATABASE_URL.
load_dotenv()

if True:  # pragma: no cover - keeps env loading before app import.
    from app import create_app


def _resolved_flask_config() -> str:
    explicit = (os.getenv("FLASK_CONFIG") or "").strip()
    if explicit:
        return explicit
    if (os.getenv("FLASK_ENV") or "").strip().lower() == "production":
        return "production"
    return "default"


app = create_app(_resolved_flask_config())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
