from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Iterable, Optional
from urllib.parse import quote

import requests

from auth_service import VaultUser, refresh_id_token

PROJECT_ID = "nexustcg-ad9d3"
DATABASE_ID = "(default)"
BASE_URL = f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/{DATABASE_ID}/documents"
REQUEST_TIMEOUT = 24


class FirestoreError(RuntimeError):
    pass


@dataclass(slots=True)
class VaultCard:
    doc_id: str
    data: dict[str, Any]


def _decode_value(value: dict[str, Any]) -> Any:
    if not isinstance(value, dict):
        return value
    if "nullValue" in value:
        return None
    if "stringValue" in value:
        return value["stringValue"]
    if "booleanValue" in value:
        return bool(value["booleanValue"])
    if "integerValue" in value:
        try:
            return int(value["integerValue"])
        except Exception:
            return 0
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "timestampValue" in value:
        return value["timestampValue"]
    if "referenceValue" in value:
        return value["referenceValue"]
    if "geoPointValue" in value:
        return value["geoPointValue"]
    if "bytesValue" in value:
        return value["bytesValue"]
    if "arrayValue" in value:
        return [_decode_value(item) for item in (value["arrayValue"].get("values") or [])]
    if "mapValue" in value:
        return {key: _decode_value(item) for key, item in (value["mapValue"].get("fields") or {}).items()}
    return None


def _encode_value(value: Any) -> dict[str, Any]:
    if value is None:
        return {"nullValue": None}
    if isinstance(value, bool):
        return {"booleanValue": value}
    if isinstance(value, int) and not isinstance(value, bool):
        return {"integerValue": str(value)}
    if isinstance(value, float):
        return {"doubleValue": value}
    if isinstance(value, str):
        return {"stringValue": value}
    if isinstance(value, (list, tuple)):
        return {"arrayValue": {"values": [_encode_value(item) for item in value]}}
    if isinstance(value, dict):
        return {"mapValue": {"fields": {str(key): _encode_value(item) for key, item in value.items()}}}
    return {"stringValue": str(value)}


def _decode_document(document: dict[str, Any]) -> VaultCard:
    name = str(document.get("name") or "")
    doc_id = name.rsplit("/", 1)[-1]
    fields = {key: _decode_value(value) for key, value in (document.get("fields") or {}).items()}
    fields["_doc_id"] = doc_id
    fields["_create_time"] = document.get("createTime")
    fields["_update_time"] = document.get("updateTime")
    return VaultCard(doc_id=doc_id, data=fields)


def _friendly_message(response: requests.Response) -> str:
    try:
        payload = response.json()
        message = payload.get("error", {}).get("message") or ""
    except Exception:
        message = ""
    if response.status_code in (401, 403):
        return "Sua sessão não tem permissão para acessar a coleção. Entre novamente se o problema continuar."
    if response.status_code == 404:
        return "A coleção ou a carta não foi encontrada no Vault."
    return message or f"Firestore respondeu HTTP {response.status_code}."


def _request(user: VaultUser, method: str, url: str, *, params=None, json=None, timeout: int = REQUEST_TIMEOUT) -> requests.Response:
    headers = {"Authorization": f"Bearer {user.id_token}", "Content-Type": "application/json"}
    try:
        response = requests.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
    except requests.RequestException as exc:
        raise FirestoreError("Não foi possível conectar ao banco do Vault.") from exc

    if response.status_code == 401 and user.refresh_token:
        try:
            refreshed = refresh_id_token(user.refresh_token)
            user.id_token = refreshed.id_token
            user.refresh_token = refreshed.refresh_token or user.refresh_token
            headers["Authorization"] = f"Bearer {user.id_token}"
            response = requests.request(method, url, headers=headers, params=params, json=json, timeout=timeout)
        except Exception:
            pass

    if not response.ok:
        raise FirestoreError(_friendly_message(response))
    return response


def list_user_cards(user: VaultUser) -> list[dict[str, Any]]:
    """Carrega todas as cartas de collections/{uid}/cards via REST autenticado."""
    uid = quote(user.uid, safe="")
    url = f"{BASE_URL}/collections/{uid}/cards"
    cards: list[dict[str, Any]] = []
    page_token = ""
    while True:
        params = {"pageSize": 300}
        if page_token:
            params["pageToken"] = page_token
        response = _request(user, "GET", url, params=params)
        payload = response.json()
        for document in payload.get("documents") or []:
            cards.append(_decode_document(document).data)
        page_token = str(payload.get("nextPageToken") or "")
        if not page_token:
            break
    return cards


def normalize_card(card: dict[str, Any]) -> dict[str, Any]:
    data = copy.deepcopy(card)
    link_myp = str(data.get("linkMyp") or data.get("Link MYP") or data.get("link_myp") or "").strip()
    name = str(data.get("name") or data.get("Nome") or "Carta sem nome")
    number = str(data.get("number") or data.get("Número") or data.get("Numeração") or "")
    collection = str(data.get("collection") or data.get("Coleção") or "")
    condition = str(data.get("condition") or data.get("Estado") or "NM").strip().upper() or "NM"
    language = str(data.get("language") or data.get("Idioma") or "")
    image = str(data.get("image") or data.get("Imagem") or "")
    image_candidates = data.get("imageCandidates") if isinstance(data.get("imageCandidates"), list) else []
    if not image and image_candidates:
        image = str(image_candidates[0] or "")
    quantity_raw = data.get("quantity", data.get("Quantidade", 1))
    try:
        quantity = max(1, int(float(quantity_raw)))
    except Exception:
        quantity = 1
    data.update({
        "_doc_id": str(data.get("_doc_id") or data.get("id") or data.get("Id") or ""),
        "name": name,
        "number": number,
        "collection": collection,
        "condition": condition,
        "language": language,
        "linkMyp": link_myp,
        "image": image,
        "quantity": quantity,
    })
    return data


def _patch_fields(user: VaultUser, doc_id: str, fields: dict[str, Any]) -> None:
    uid = quote(user.uid, safe="")
    card_id = quote(str(doc_id), safe="")
    url = f"{BASE_URL}/collections/{uid}/cards/{card_id}"
    params = [("updateMask.fieldPaths", key) for key in fields.keys()]
    payload = {"fields": {key: _encode_value(value) for key, value in fields.items()}}
    _request(user, "PATCH", url, params=params, json=payload)


def build_quote_patch(card: dict[str, Any], quote_result: dict[str, Any]) -> dict[str, Any]:
    prices = quote_result.get("prices") or {}
    offers = quote_result.get("offers") or {}
    quoted_at = str(quote_result.get("quotedAt") or "")
    low = prices.get("conditionLowest")
    if low is None:
        low = prices.get("visibleLowest")
    avg = prices.get("conditionAverage")
    if avg is None:
        avg = prices.get("visibleAverage")

    history = list(card.get("priceHistory") or []) if isinstance(card.get("priceHistory"), list) else []
    entry = {
        "date": quoted_at,
        "source": "MYP",
        "cheapestGeneral": low,
        "averageGeneral": avg,
        "minimum": prices.get("minimum"),
        "condition": quote_result.get("condition") or card.get("condition") or "",
        "visibleOffers": int(offers.get("visibleTotal") or 0),
    }
    history.append(entry)
    history = history[-120:]

    patch = {
        "pricingSchemaVersion": 3,
        "pricingSource": "MYP",
        "cheapestGeneralPrice": low,
        "averageGeneralPrice": avg,
        "otherOffers": int(offers.get("visibleTotal") or 0),
        "totalOffers": int(offers.get("visibleTotal") or 0),
        "lastQuotedAt": quoted_at,
        "lastQuoteAttemptAt": quoted_at,
        "lastQuoteSource": "MYP",
        "lastQuoteStatus": "success",
        "lastQuoteError": "",
        "priceHistory": history,
    }
    if prices.get("minimum") is not None:
        patch["minimumPrice"] = prices.get("minimum")
    return patch


def save_quote(user: VaultUser, card: dict[str, Any], quote_result: dict[str, Any]) -> None:
    doc_id = str(card.get("_doc_id") or "")
    if not doc_id:
        raise FirestoreError("Esta carta não tem identificador de documento no Firestore.")
    _patch_fields(user, doc_id, build_quote_patch(card, quote_result))
