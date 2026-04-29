import os

from dotenv import load_dotenv

# Load ``.env`` before ``from app import …`` so ``app.config`` sees POSTGRES_* / DATABASE_URL.
load_dotenv()

if True:  # pragma: no cover - keeps env loading before app import.
    from app import create_app

app = create_app(os.getenv("FLASK_CONFIG", "default"))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
