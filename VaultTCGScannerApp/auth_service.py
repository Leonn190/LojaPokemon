from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import requests

FIREBASE_API_KEY = "AIzaSyAH2-yNZl048tTL57BCq7gdh82YBZH7GmU"
SIGN_IN_URL = "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
SECURE_TOKEN_URL = "https://securetoken.googleapis.com/v1/token"
REQUEST_TIMEOUT = 18


@dataclass(slots=True)
class VaultUser:
    uid: str
    email: str
    id_token: str
    refresh_token: str
    display_name: str = ""


class AuthError(RuntimeError):
    pass


def _friendly_firebase_error(code: str) -> str:
    code = (code or "").strip().upper()
    messages = {
        "EMAIL_NOT_FOUND": "Não encontrei uma conta com esse e-mail.",
        "INVALID_PASSWORD": "Senha incorreta.",
        "INVALID_LOGIN_CREDENTIALS": "E-mail ou senha incorretos.",
        "USER_DISABLED": "Esta conta está desativada.",
        "TOO_MANY_ATTEMPTS_TRY_LATER": "Muitas tentativas. Aguarde um pouco e tente novamente.",
        "INVALID_EMAIL": "Informe um e-mail válido.",
        "MISSING_PASSWORD": "Informe sua senha.",
    }
    return messages.get(code, "Não foi possível entrar na sua conta do Vault TCG.")


def sign_in(email: str, password: str, session: Optional[requests.Session] = None) -> VaultUser:
    email = str(email or "").strip()
    password = str(password or "")
    if not email:
        raise AuthError("Informe seu e-mail.")
    if not password:
        raise AuthError("Informe sua senha.")

    http = session or requests.Session()
    try:
        response = http.post(
            SIGN_IN_URL,
            params={"key": FIREBASE_API_KEY},
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AuthError("Não foi possível conectar ao Firebase. Verifique sua internet.") from exc

    if not response.ok:
        try:
            payload = response.json()
            code = payload.get("error", {}).get("message", "")
        except Exception:
            code = ""
        raise AuthError(_friendly_firebase_error(code))

    payload = response.json()
    return VaultUser(
        uid=str(payload.get("localId") or ""),
        email=str(payload.get("email") or email),
        id_token=str(payload.get("idToken") or ""),
        refresh_token=str(payload.get("refreshToken") or ""),
        display_name=str(payload.get("displayName") or ""),
    )


def refresh_id_token(refresh_token: str, session: Optional[requests.Session] = None) -> VaultUser:
    token = str(refresh_token or "").strip()
    if not token:
        raise AuthError("Sessão expirada. Entre novamente.")
    http = session or requests.Session()
    try:
        response = http.post(
            SECURE_TOKEN_URL,
            params={"key": FIREBASE_API_KEY},
            data={"grant_type": "refresh_token", "refresh_token": token},
            timeout=REQUEST_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise AuthError("Não foi possível renovar sua sessão do Vault.") from exc
    if not response.ok:
        raise AuthError("Sua sessão expirou. Entre novamente.")
    payload = response.json()
    return VaultUser(
        uid=str(payload.get("user_id") or ""),
        email="",
        id_token=str(payload.get("id_token") or ""),
        refresh_token=str(payload.get("refresh_token") or token),
        display_name="",
    )
