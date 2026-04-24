from app.users.models import User


def authenticate_user(email: str, password: str) -> User | None:
    user = User.query.filter_by(email=email).first()
    if not user:
        return None

    if not user.is_active:
        return None

    if not user.check_password(password):
        return None

    return user
