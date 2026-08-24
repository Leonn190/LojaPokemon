#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pokemon_card_scanner.py

Scanner de cartas Pokémon usando webcam.

Como funciona:
1) Abre a câmera com OpenCV.
2) Você posiciona a carta dentro da moldura.
3) Ao pressionar ESPAÇO, o programa:
   - recorta a carta;
   - usa OCR (EasyOCR) para procurar a numeração, como 106/167;
   - consulta a API pública Pokémon TCG;
   - filtra candidatos pela numeração/total;
   - compara visualmente a foto com as imagens oficiais;
   - consulta a API oficial do MYP Cards;
   - cruza nome + numeração + coleção e devolve o link exato do produto.

Teclas:
    ESPAÇO = identificar a carta e localizar no MYP
    O      = abrir o link do MYP no navegador (quando encontrado)
    R      = limpar resultado
    Q/ESC  = sair

Dependências:
    pip install opencv-python easyocr requests numpy

Observações:
- Na primeira execução, o EasyOCR pode baixar os modelos de reconhecimento.
- É necessário acesso à internet para consultar a base Pokémon TCG.
- Opcionalmente, defina a variável POKEMONTCG_API_KEY para aumentar o limite
  de requisições da API Pokémon TCG.
- O scanner tenta a API oficial do MYP Cards. Se sua instalação receber 401/403,
  defina MYPCARDS_API_TOKEN com um token fornecido pelo MYP. Sem token, o scanner
  ainda tenta um fallback por busca pública na web.
"""

from __future__ import annotations

import os
import re
import sys
import time
import math
import difflib
import html
import unicodedata
import webbrowser
from urllib.parse import quote, unquote
from dataclasses import dataclass
from typing import Optional

MISSING = []
try:
    import cv2
except ImportError:
    MISSING.append("opencv-python")
try:
    import numpy as np
except ImportError:
    MISSING.append("numpy")
try:
    import requests
except ImportError:
    MISSING.append("requests")
try:
    import easyocr
except ImportError:
    MISSING.append("easyocr")

# Em modo biblioteca o app principal decide como exibir dependências ausentes.
# Mantemos a lista MISSING disponível, mas não encerramos o processo no import.


API_URL = "https://api.pokemontcg.io/v2/cards"
MYP_API_BASE = "https://mypcards.com/api/v1"
MYP_PRODUCT_RE = re.compile(
    r"https?://(?:www\.)?mypcards\.com/pokemon/produto/\d+/[^\s\"'<>?&]+",
    re.IGNORECASE,
)
REQUEST_TIMEOUT = 12
MAX_API_PAGES = 5
MAX_CANDIDATES_FOR_IMAGE_COMPARE = 15

# Relação aproximada de uma carta Pokémon: 63 x 88 mm.
CARD_ASPECT = 63 / 88

# Padrões comuns de numeração.
NUMBER_TOTAL_RE = re.compile(
    r"(?<!\d)(\d{1,3})\s*[/|Iil]\s*(\d{2,3})(?!\d)",
    re.IGNORECASE,
)
PROMO_RE = re.compile(
    r"\b(?:SWSH|SVP|SM|XY|BW|DP|HGSS|MEP)\s*[- ]?\s*\d{1,3}\b",
    re.IGNORECASE,
)
SPECIAL_NUMBER_RE = re.compile(
    r"\b(?:TG|GG|RC|SH|SV)\s*[- ]?\s*\d{1,3}\b",
    re.IGNORECASE,
)


@dataclass
class OCRLine:
    text: str
    confidence: float
    box: list


@dataclass
class CardCandidate:
    card: dict
    text_score: float = 0.0
    image_score: float = 0.0
    final_score: float = 0.0


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def api_headers() -> dict:
    headers = {"User-Agent": "PokemonCardCameraScanner/1.0"}
    api_key = os.getenv("POKEMONTCG_API_KEY", "").strip()
    if api_key:
        headers["X-Api-Key"] = api_key
    return headers


def myp_headers() -> dict:
    """Headers para a API oficial do MYP Cards."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                      "AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Referer": "https://mypcards.com/pokemon",
    }
    token = os.getenv("MYPCARDS_API_TOKEN", "").strip()
    if token:
        headers["X-Api-Token"] = token
    return headers


def _int_or_none(value) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _collector_numbers_from_myp(card: dict) -> list[tuple[str, Optional[int]]]:
    """Extrai numerações conhecidas dos campos retornados pelo MYP."""
    texts = []
    for key in ("card_code", "number", "collector_number"):
        value = card.get(key)
        if value:
            texts.append(str(value))

    for value in card.get("deck_labels") or []:
        if value:
            texts.append(str(value))

    out: list[tuple[str, Optional[int]]] = []
    seen = set()
    for text in texts:
        promo_text = re.sub(r"[_]+", " ", text)
        for m in NUMBER_TOTAL_RE.finditer(text):
            pair = (str(int(m.group(1))), int(m.group(2)))
            if pair not in seen:
                seen.add(pair)
                out.append(pair)

        # Promo/especial sem total, como SWSH144 ou XY108.
        compact = re.sub(r"[^A-Za-z0-9]", "", text).upper()
        for rx in (PROMO_RE, SPECIAL_NUMBER_RE):
            m = rx.search(promo_text)
            if m:
                number = re.sub(r"[\s-]+", "", m.group(0)).upper()
                pair = (number, None)
                if pair not in seen:
                    seen.add(pair)
                    out.append(pair)
        if compact and re.fullmatch(r"(?:SWSH|SVP|SM|XY|BW|DP|HGSS|MEP)\d{1,3}", compact):
            pair = (compact, None)
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
    return out

def _target_set_codes(card: dict) -> set[str]:
    set_data = card.get("set") or {}
    values = {
        set_data.get("ptcgoCode"),
        set_data.get("id"),
    }
    return {str(v).strip().upper() for v in values if v}

def _target_tcgplayer_id(card: dict) -> Optional[int]:
    tcg = card.get("tcgplayer") or {}
    return _int_or_none(tcg.get("productId"))

def score_myp_candidate(target: dict, candidate: dict) -> float:
    """Pontua quão bem um produto MYP corresponde à carta reconhecida."""
    score = 0.0

    target_name = normalize_text(target.get("name", ""))
    names = [candidate.get("name_en"), candidate.get("name_pt")]
    normalized_names = [normalize_text(x or "") for x in names if x]
    if target_name and target_name in normalized_names:
        score += 35.0
    elif target_name and normalized_names:
        score += 20.0 * max(
            difflib.SequenceMatcher(None, target_name, n).ratio()
            for n in normalized_names
        )

    target_tcg = _target_tcgplayer_id(target)
    myp_tcg = _int_or_none(candidate.get("tcg_productId"))
    if target_tcg is not None and myp_tcg == target_tcg:
        score += 120.0

    target_codes = _target_set_codes(target)
    myp_set = str(candidate.get("edition_code") or "").strip().upper()
    if myp_set and myp_set in target_codes:
        score += 55.0

    target_number = str(target.get("number") or "").upper().replace("-", "")
    target_total = set_printed_total(target)
    for cand_number, cand_total in _collector_numbers_from_myp(candidate):
        cn = str(cand_number).upper().replace("-", "")
        if cn != target_number:
            continue
        if target_total is not None and cand_total == target_total:
            score += 80.0
            break
        if cand_total is None:
            score += 45.0
            break
        score += 30.0
        break

    return score

def _clean_myp_link(link: str) -> Optional[str]:
    if not link:
        return None
    link = html.unescape(str(link)).strip()
    link = unquote(link)
    m = MYP_PRODUCT_RE.search(link)
    if not m:
        return None
    return m.group(0).rstrip("/.,);]")

def fetch_myp_cards_by_name(name: str) -> list[dict]:
    """Busca todas as impressões com o nome exato na API oficial do MYP."""
    url = f"{MYP_API_BASE}/pokemon/carta/{quote(name, safe='')}"
    response = requests.get(url, headers=myp_headers(), timeout=REQUEST_TIMEOUT)
    if response.status_code in (401, 403):
        raise PermissionError(
            "A API do MYP exigiu X-Api-Token. "
            "Defina MYPCARDS_API_TOKEN ou use o fallback de busca pública."
        )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, dict):
        cards = payload.get("cards") or payload.get("data") or []
        return cards if isinstance(cards, list) else []
    return payload if isinstance(payload, list) else []

def lookup_myp_official(target: dict) -> tuple[Optional[str], dict]:
    """Localiza o produto exato pela API oficial do MYP."""
    info = {"source": "myp_api", "candidates": 0, "score": 0.0, "error": None}
    name = str(target.get("name") or "").strip()
    if not name:
        info["error"] = "Carta sem nome para consultar no MYP."
        return None, info

    names_to_try = [name]
    # Algumas bases alternam hífen e espaço em nomes antigos (ex.: Machamp-EX).
    if "-" in name:
        names_to_try.append(name.replace("-", " "))
    if " " in name:
        names_to_try.append(re.sub(r"\s+(EX|GX|V|VMAX|VSTAR)$", r"-\1", name, flags=re.I))

    all_cards: list[dict] = []
    seen_ids = set()
    last_error = None
    for search_name in dict.fromkeys(x for x in names_to_try if x):
        try:
            cards = fetch_myp_cards_by_name(search_name)
        except Exception as exc:
            last_error = str(exc)
            continue
        for c in cards:
            key = c.get("internal_code") or c.get("link") or repr(c)
            if key in seen_ids:
                continue
            seen_ids.add(key)
            all_cards.append(c)

    info["candidates"] = len(all_cards)
    if not all_cards:
        info["error"] = last_error or "Nenhum produto retornado pela API do MYP."
        return None, info

    ranked = sorted(
        ((score_myp_candidate(target, c), c) for c in all_cards),
        key=lambda x: x[0],
        reverse=True,
    )
    best_score, best = ranked[0]
    info["score"] = best_score
    info["internal_code"] = best.get("internal_code")

    link = _clean_myp_link(best.get("link") or "")
    if not link and best.get("internal_code"):
        slug = best.get("slug_pt") or best.get("slug_en") or normalize_text(name).replace(" ", "-")
        link = f"https://mypcards.com/pokemon/produto/{best['internal_code']}/{slug}"

    # Exige pelo menos uma combinação bem específica, evitando devolver edição errada.
    if link and best_score >= 70:
        return link, info

    info["error"] = (
        f"A API retornou candidatos, mas o melhor match ficou inseguro "
        f"(score {best_score:.0f})."
    )
    return None, info

def _extract_myp_urls_from_search_html(text: str) -> list[str]:
    """Extrai URLs de produto MYP de uma página de resultados de busca."""
    variants = [text, html.unescape(text)]
    # DuckDuckGo costuma colocar o destino em ?uddg=<url codificada>.
    try:
        variants.append(unquote(html.unescape(text)))
    except Exception:
        pass

    urls = []
    seen = set()
    for variant in variants:
        for m in MYP_PRODUCT_RE.finditer(variant):
            url = _clean_myp_link(m.group(0))
            if url and url not in seen:
                seen.add(url)
                urls.append(url)

        for raw in re.findall(r"uddg=([^&\"']+)", variant, flags=re.I):
            try:
                url = _clean_myp_link(unquote(raw))
            except Exception:
                url = None
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls

def lookup_myp_web_fallback(target: dict) -> tuple[Optional[str], dict]:
    """Fallback sem token: usa busca pública e valida a numeração no resultado."""
    info = {"source": "web_search", "candidates": 0, "score": 0.0, "error": None}
    name = str(target.get("name") or "").strip()
    number = str(target.get("number") or "").strip()
    total = set_printed_total(target)
    set_codes = sorted(_target_set_codes(target))
    number_text = f"{number}/{total}" if number and total else number
    query = f'site:mypcards.com/pokemon/produto "{name}" "{number_text}"'
    if set_codes:
        query += f' "{set_codes[0]}"'

    search_urls = [
        ("duckduckgo", "https://html.duckduckgo.com/html/", {"q": query}),
        ("bing", "https://www.bing.com/search", {"q": query, "count": 10}),
    ]

    collected = []
    seen = set()
    last_error = None
    for source, url, params in search_urls:
        try:
            response = requests.get(
                url,
                params=params,
                headers={
                    "User-Agent": myp_headers()["User-Agent"],
                    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
                },
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            for product_url in _extract_myp_urls_from_search_html(response.text):
                if product_url not in seen:
                    seen.add(product_url)
                    collected.append(product_url)
            if collected:
                info["search_engine"] = source
                break
        except Exception as exc:
            last_error = str(exc)

    info["candidates"] = len(collected)
    if not collected:
        info["error"] = last_error or "Busca pública não retornou produto do MYP."
        return None, info

    # A consulta já contém nome + número + coleção; o primeiro resultado de produto
    # costuma ser o match correto. Quando houver vários, tenta validar pelo HTML do MYP.
    target_norm = normalize_text(name)
    set_codes_upper = set(_target_set_codes(target))
    scored = []
    for product_url in collected[:8]:
        score = 0.0
        try:
            r = requests.get(product_url, headers=myp_headers(), timeout=REQUEST_TIMEOUT)
            if r.ok:
                page = html.unescape(r.text)
                page_norm = normalize_text(page)
                if target_norm and target_norm in page_norm:
                    score += 30
                if number_text and number_text.lower() in page.lower():
                    score += 70
                for code in set_codes_upper:
                    if re.search(rf"(?<![A-Za-z0-9]){re.escape(code)}(?![A-Za-z0-9])", page, flags=re.I):
                        score += 40
                        break
        except Exception:
            pass
        scored.append((score, product_url))

    scored.sort(reverse=True, key=lambda x: x[0])
    best_score, best_url = scored[0]
    info["score"] = best_score
    # Mesmo sem conseguir abrir a página, a busca exata já é suficientemente restritiva.
    if best_score >= 70 or (best_score == 0 and len(collected) == 1):
        return best_url, info

    info["error"] = "Encontrei resultados do MYP, mas não consegui validar a impressão exata."
    return None, info

def lookup_myp_link(target: dict) -> tuple[Optional[str], dict]:
    """API oficial primeiro; busca pública como fallback."""
    api_link, api_info = lookup_myp_official(target)
    if api_link:
        return api_link, api_info

    web_link, web_info = lookup_myp_web_fallback(target)
    if web_link:
        web_info["api_error"] = api_info.get("error")
        return web_link, web_info

    return None, {
        "source": None,
        "candidates": 0,
        "score": 0.0,
        "error": web_info.get("error") or api_info.get("error") or "Não localizado no MYP.",
        "api_error": api_info.get("error"),
    }


def get_card_roi(frame: np.ndarray) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """
    Cria uma moldura central em formato de carta e devolve o recorte.
    """
    h, w = frame.shape[:2]

    max_h = int(h * 0.82)
    max_w = int(w * 0.72)

    card_h = max_h
    card_w = int(card_h * CARD_ASPECT)

    if card_w > max_w:
        card_w = max_w
        card_h = int(card_w / CARD_ASPECT)

    x1 = (w - card_w) // 2
    y1 = (h - card_h) // 2
    x2 = x1 + card_w
    y2 = y1 + card_h

    roi = frame[y1:y2, x1:x2].copy()
    return roi, (x1, y1, x2, y2)


def preprocess_for_ocr(card_img: np.ndarray) -> list[np.ndarray]:
    """
    Gera algumas versões do recorte para melhorar a chance do OCR ler
    a numeração minúscula no rodapé.
    """
    h, w = card_img.shape[:2]

    # Upscale geral.
    scale = max(1.0, 1000 / max(h, 1))
    full = cv2.resize(
        card_img,
        None,
        fx=scale,
        fy=scale,
        interpolation=cv2.INTER_CUBIC,
    )

    # Rodapé: onde geralmente fica a numeração.
    bottom = card_img[int(h * 0.70):h, :]
    bottom = cv2.resize(
        bottom,
        None,
        fx=max(2.0, 1200 / max(w, 1)),
        fy=max(2.0, 1200 / max(w, 1)),
        interpolation=cv2.INTER_CUBIC,
    )

    gray = cv2.cvtColor(bottom, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    sharp = cv2.addWeighted(gray, 1.8, cv2.GaussianBlur(gray, (0, 0), 3), -0.8, 0)
    adaptive = cv2.adaptiveThreshold(
        sharp,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        31,
        9,
    )

    return [full, bottom, sharp, adaptive]


def run_ocr(reader: easyocr.Reader, card_img: np.ndarray) -> list[OCRLine]:
    """
    Executa OCR em múltiplas versões da imagem e remove repetições.
    """
    lines: list[OCRLine] = []
    seen: set[str] = set()

    for img in preprocess_for_ocr(card_img):
        try:
            results = reader.readtext(
                img,
                detail=1,
                paragraph=False,
                decoder="greedy",
                text_threshold=0.45,
                low_text=0.25,
                link_threshold=0.35,
            )
        except Exception:
            continue

        for box, text, conf in results:
            clean = str(text).strip()
            if not clean:
                continue
            key = normalize_text(clean)
            if key and key not in seen:
                seen.add(key)
                lines.append(OCRLine(clean, float(conf), box))

    lines.sort(key=lambda x: x.confidence, reverse=True)
    return lines


def extract_number(lines: list[OCRLine]) -> tuple[Optional[str], Optional[int]]:
    """
    Retorna (numero_da_carta, total_impresso).

    Exemplos:
      "106/167" -> ("106", 167)
      "SWSH123" -> ("SWSH123", None)
      "TG12"    -> ("TG12", None)
    """
    # Prioriza linhas com maior confiança.
    for line in lines:
        text = (
            line.text.replace("O", "0")
            .replace("o", "0")
        )
        m = NUMBER_TOTAL_RE.search(text)
        if m:
            number = str(int(m.group(1)))
            total = int(m.group(2))
            return number, total

    combined = " ".join(line.text for line in lines)

    promo = PROMO_RE.search(combined)
    if promo:
        number = re.sub(r"[\s-]+", "", promo.group(0)).upper()
        return number, None

    special = SPECIAL_NUMBER_RE.search(combined)
    if special:
        number = re.sub(r"[\s-]+", "", special.group(0)).upper()
        return number, None

    return None, None


def probable_name_text(lines: list[OCRLine]) -> str:
    """
    Junta textos úteis do OCR para ajudar no ranking por nome.
    """
    ignore = {
        "basic", "stage", "hp", "pokemon", "trainer", "energy",
        "weakness", "resistance", "retreat", "illustrator",
    }

    useful = []
    for line in lines:
        txt = line.text.strip()
        n = normalize_text(txt)
        if len(n) < 2:
            continue
        if n in ignore:
            continue
        if re.fullmatch(r"\d+", n):
            continue
        if NUMBER_TOTAL_RE.search(txt):
            continue
        if len(txt) > 45:
            continue
        useful.append(txt)

    return " ".join(useful[:12])


def fetch_cards_by_number(number: str) -> list[dict]:
    """
    Consulta a API Pokémon TCG pelo número da carta.
    """
    cards: list[dict] = []
    page = 1

    # A API aceita busca Lucene-like: q=number:106
    query = f'number:"{number}"'

    while page <= MAX_API_PAGES:
        params = {
            "q": query,
            "page": page,
            "pageSize": 250,
            "select": "id,name,number,rarity,images,set,supertype,subtypes,tcgplayer",
        }

        response = requests.get(
            API_URL,
            params=params,
            headers=api_headers(),
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()

        batch = payload.get("data", [])
        cards.extend(batch)

        total_count = int(payload.get("totalCount", len(cards)))
        if len(cards) >= total_count or not batch:
            break
        page += 1

    return cards


def set_printed_total(card: dict) -> Optional[int]:
    set_data = card.get("set") or {}

    for key in ("printedTotal", "total"):
        value = set_data.get(key)
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            pass
    return None


def filter_by_total(cards: list[dict], total: Optional[int]) -> list[dict]:
    if total is None:
        return cards

    exact = [c for c in cards if set_printed_total(c) == total]
    return exact if exact else cards


def text_similarity(card: dict, ocr_text: str) -> float:
    """
    Mede quanto o nome oficial aparece no texto reconhecido.
    """
    name = normalize_text(card.get("name", ""))
    text = normalize_text(ocr_text)

    if not name or not text:
        return 0.0

    if name in text:
        return 1.0

    tokens = text.split()
    name_tokens = name.split()

    # Melhor janela de palavras do OCR contra o nome.
    best = difflib.SequenceMatcher(None, name, text).ratio()

    if name_tokens and tokens:
        size = max(1, len(name_tokens))
        for i in range(max(1, len(tokens) - size + 1)):
            window = " ".join(tokens[i:i + size])
            best = max(best, difflib.SequenceMatcher(None, name, window).ratio())

    return float(best)


def download_candidate_image(url: str) -> Optional[np.ndarray]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "PokemonCardCameraScanner/1.0"},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        arr = np.frombuffer(response.content, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        return img
    except Exception:
        return None


def orb_similarity(camera_img: np.ndarray, official_img: np.ndarray) -> float:
    """
    Compara os detalhes visuais das duas cartas com ORB.

    Não depende de o texto estar no mesmo idioma; arte, bordas, símbolos e
    estrutura costumam gerar pontos em comum.
    """
    if camera_img is None or official_img is None:
        return 0.0

    cam = cv2.resize(camera_img, (450, 630), interpolation=cv2.INTER_AREA)
    off = cv2.resize(official_img, (450, 630), interpolation=cv2.INTER_AREA)

    cam_gray = cv2.cvtColor(cam, cv2.COLOR_BGR2GRAY)
    off_gray = cv2.cvtColor(off, cv2.COLOR_BGR2GRAY)

    # CLAHE ajuda com luz irregular da webcam.
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    cam_gray = clahe.apply(cam_gray)
    off_gray = clahe.apply(off_gray)

    orb = cv2.ORB_create(
        nfeatures=1800,
        scaleFactor=1.2,
        nlevels=8,
        edgeThreshold=15,
        patchSize=31,
        fastThreshold=10,
    )

    kp1, des1 = orb.detectAndCompute(cam_gray, None)
    kp2, des2 = orb.detectAndCompute(off_gray, None)

    if des1 is None or des2 is None or len(kp1) < 8 or len(kp2) < 8:
        return 0.0

    matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)

    try:
        pairs = matcher.knnMatch(des1, des2, k=2)
    except cv2.error:
        return 0.0

    good = []
    for pair in pairs:
        if len(pair) != 2:
            continue
        m, n = pair
        if m.distance < 0.72 * n.distance:
            good.append(m)

    # Normaliza de forma conservadora.
    denom = max(25.0, min(len(kp1), len(kp2)) * 0.10)
    score = min(1.0, len(good) / denom)

    # Pequeno bônus se os melhores matches forem muito próximos.
    if good:
        avg_dist = sum(m.distance for m in sorted(good, key=lambda x: x.distance)[:20])
        avg_dist /= min(20, len(good))
        quality = max(0.0, min(1.0, 1.0 - avg_dist / 80.0))
        score = min(1.0, 0.78 * score + 0.22 * quality)

    return float(score)


def rank_candidates(
    cards: list[dict],
    card_img: np.ndarray,
    ocr_text: str,
) -> list[CardCandidate]:
    ranked = [
        CardCandidate(card=c, text_score=text_similarity(c, ocr_text))
        for c in cards
    ]

    # Primeiro usa texto para limitar downloads quando existem muitos candidatos.
    ranked.sort(key=lambda x: x.text_score, reverse=True)
    image_pool = ranked[:MAX_CANDIDATES_FOR_IMAGE_COMPARE]

    for item in image_pool:
        images = item.card.get("images") or {}
        image_url = images.get("small") or images.get("large")
        if not image_url:
            continue

        official = download_candidate_image(image_url)
        if official is None:
            continue

        item.image_score = orb_similarity(card_img, official)

    # Para cartas Pokémon, imagem tem peso maior: funciona melhor em BR/ING.
    for item in ranked:
        item.final_score = 0.30 * item.text_score + 0.70 * item.image_score

    ranked.sort(key=lambda x: x.final_score, reverse=True)
    return ranked


def identify_card(reader: easyocr.Reader, card_img: np.ndarray) -> tuple[Optional[CardCandidate], dict]:
    debug = {
        "number": None,
        "total": None,
        "ocr": [],
        "candidate_count": 0,
        "myp_link": None,
        "myp": {},
        "error": None,
    }

    lines = run_ocr(reader, card_img)
    debug["ocr"] = [line.text for line in lines]

    number, total = extract_number(lines)
    debug["number"] = number
    debug["total"] = total

    if not number:
        debug["error"] = (
            "Nao consegui ler a numeracao. Aproxime a carta, "
            "evite reflexos e tente novamente."
        )
        return None, debug

    try:
        cards = fetch_cards_by_number(number)
    except requests.RequestException as exc:
        debug["error"] = f"Erro ao consultar a base Pokemon TCG: {exc}"
        return None, debug
    except Exception as exc:
        debug["error"] = f"Erro inesperado na consulta: {exc}"
        return None, debug

    cards = filter_by_total(cards, total)
    debug["candidate_count"] = len(cards)

    if not cards:
        suffix = f"/{total}" if total else ""
        debug["error"] = f"Nenhuma carta encontrada para {number}{suffix}."
        return None, debug

    ocr_text = probable_name_text(lines)
    ranked = rank_candidates(cards, card_img, ocr_text)

    if not ranked:
        debug["error"] = "Encontrei candidatos, mas nao consegui compara-los."
        return None, debug

    return ranked[0], debug


def fit_text(text: str, max_chars: int = 62) -> list[str]:
    """
    Quebra texto para caber no overlay.
    """
    words = str(text).split()
    rows = []
    current = ""

    for word in words:
        attempt = word if not current else current + " " + word
        if len(attempt) <= max_chars:
            current = attempt
        else:
            if current:
                rows.append(current)
            current = word

    if current:
        rows.append(current)
    return rows or [""]


def draw_status(
    frame: np.ndarray,
    rect: tuple[int, int, int, int],
    status: str,
    result: Optional[CardCandidate],
    debug: dict,
) -> np.ndarray:
    x1, y1, x2, y2 = rect
    out = frame.copy()

    # Moldura.
    cv2.rectangle(out, (x1, y1), (x2, y2), (255, 255, 255), 2)

    # Cantos mais fortes para facilitar enquadramento.
    corner = 28
    thick = 4
    for x, y, sx, sy in [
        (x1, y1, 1, 1),
        (x2, y1, -1, 1),
        (x1, y2, 1, -1),
        (x2, y2, -1, -1),
    ]:
        cv2.line(out, (x, y), (x + sx * corner, y), (255, 255, 255), thick)
        cv2.line(out, (x, y), (x, y + sy * corner), (255, 255, 255), thick)

    h, w = out.shape[:2]

    # Faixa superior.
    overlay = out.copy()
    cv2.rectangle(overlay, (0, 0), (w, 78), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, out, 0.45, 0, out)

    cv2.putText(
        out,
        "VAULT TCG - Scanner Pokemon",
        (18, 29),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.72,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(
        out,
        "ESPACO: identificar | O: abrir MYP | R: limpar | Q/ESC: sair",
        (18, 58),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.50,
        (230, 230, 230),
        1,
        cv2.LINE_AA,
    )

    # Faixa inferior.
    lines = []
    if status == "ready":
        lines = ["Posicione a carta inteira na moldura e pressione ESPACO."]
    elif status == "scanning":
        lines = ["Analisando carta..."]
    elif status == "error":
        lines = fit_text(debug.get("error") or "Nao foi possivel identificar.")
    elif status == "found" and result:
        card = result.card
        set_data = card.get("set") or {}

        set_name = set_data.get("name", "?")
        rarity = card.get("rarity") or "Nao informada"
        number = card.get("number", "?")
        printed_total = set_data.get("printedTotal") or set_data.get("total") or "?"
        confidence = round(result.final_score * 100)

        lines = [
            f"Nome: {card.get('name', '?')}",
            f"Numeracao: {number}/{printed_total}",
            f"Colecao: {set_name}",
            f"Raridade: {rarity}",
            f"Confianca visual/texto: {confidence}%",
        ]

        myp_link = debug.get("myp_link")
        if myp_link:
            lines.append("MYP: encontrado - pressione O para abrir")
            lines.extend(fit_text(myp_link, max_chars=76))
        elif debug.get("myp"):
            myp_error = (debug.get("myp") or {}).get("error") or "link nao encontrado"
            lines.extend(fit_text(f"MYP: {myp_error}", max_chars=76))

    panel_h = 25 + 27 * len(lines)
    y_start = max(0, h - panel_h)

    overlay = out.copy()
    cv2.rectangle(overlay, (0, y_start), (w, h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.62, out, 0.38, 0, out)

    y = y_start + 26
    for line in lines:
        cv2.putText(
            out,
            line,
            (18, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.57,
            (255, 255, 255),
            1,
            cv2.LINE_AA,
        )
        y += 27

    return out


def open_camera(index: int = 0) -> cv2.VideoCapture:
    if os.name == "nt":
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(index)

    if not cap.isOpened():
        # Segunda tentativa sem backend específico.
        cap.release()
        cap = cv2.VideoCapture(index)

    return cap


def main() -> None:
    print("=" * 66)
    print("VAULT TCG - SCANNER DE CARTAS POKEMON")
    print("=" * 66)
    print("Inicializando OCR...")
    print("Na primeira execucao o EasyOCR pode baixar os modelos.\n")

    try:
        reader = easyocr.Reader(["pt", "en"], gpu=False)
    except Exception:
        # Algumas instalações/modelos aceitam melhor apenas inglês.
        print("Aviso: usando modelo OCR em ingles.")
        reader = easyocr.Reader(["en"], gpu=False)

    cap = open_camera(0)

    if not cap.isOpened():
        print("Nao foi possivel abrir a camera.")
        print("Verifique se outra aplicacao esta usando a webcam.")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

    window = "Vault TCG - Scanner Pokemon"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1100, 760)

    status = "ready"
    result: Optional[CardCandidate] = None
    debug: dict = {}

    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                print("Falha ao ler a camera.")
                break

            # Espelhamento é mais natural para posicionar a carta.
            frame = cv2.flip(frame, 1)

            roi, rect = get_card_roi(frame)
            display = draw_status(frame, rect, status, result, debug)
            cv2.imshow(window, display)

            key = cv2.waitKey(1) & 0xFF

            if key in (ord("q"), ord("Q"), 27):
                break

            if key in (ord("o"), ord("O")):
                myp_link = debug.get("myp_link")
                if myp_link:
                    print("Abrindo MYP:", myp_link)
                    try:
                        webbrowser.open(myp_link)
                    except Exception as exc:
                        print("Nao foi possivel abrir o navegador:", exc)

            if key in (ord("r"), ord("R")):
                status = "ready"
                result = None
                debug = {}

            if key == 32:  # ESPAÇO
                status = "scanning"
                result = None
                debug = {}

                # Mostra "analisando" imediatamente.
                analyzing = draw_status(frame, rect, status, result, debug)
                cv2.imshow(window, analyzing)
                cv2.waitKey(1)

                # Usa um novo recorte sem a moldura desenhada.
                card_img = roi.copy()

                started = time.time()
                best, debug = identify_card(reader, card_img)
                elapsed = time.time() - started

                print("\n--- SCAN ---")
                print("OCR:", debug.get("ocr", []))
                print("Numero:", debug.get("number"))
                print("Total:", debug.get("total"))
                print("Candidatos:", debug.get("candidate_count"))
                print(f"Tempo: {elapsed:.2f}s")

                if best is None:
                    status = "error"
                    print("Erro:", debug.get("error"))
                else:
                    result = best
                    card = best.card

                    print("Consultando MYP Cards...")
                    myp_link, myp_info = lookup_myp_link(card)
                    debug["myp_link"] = myp_link
                    debug["myp"] = myp_info
                    status = "found"

                    set_data = card.get("set") or {}
                    print("Identificada:", card.get("name"))
                    print("Numeracao:", card.get("number"))
                    print("Colecao:", set_data.get("name"))
                    print("Raridade:", card.get("rarity"))
                    print(
                        "Score:",
                        f"{best.final_score:.3f}",
                        f"(texto={best.text_score:.3f}, imagem={best.image_score:.3f})",
                    )
                    if myp_link:
                        print("MYP:", myp_link)
                        print(
                            "Fonte MYP:", myp_info.get("source"),
                            "| candidatos:", myp_info.get("candidates"),
                            "| score:", myp_info.get("score"),
                        )
                    else:
                        print("MYP: link nao encontrado")
                        print("Motivo:", myp_info.get("error"))
                        if myp_info.get("api_error"):
                            print("API MYP:", myp_info.get("api_error"))

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
