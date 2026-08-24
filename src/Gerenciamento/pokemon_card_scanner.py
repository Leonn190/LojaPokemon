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
   - mostra o resultado mais provável.

Teclas:
    ESPAÇO = identificar a carta
    R      = limpar resultado
    Q/ESC  = sair

Dependências:
    pip install opencv-python easyocr requests numpy

Observações:
- Na primeira execução, o EasyOCR pode baixar os modelos de reconhecimento.
- É necessário acesso à internet para consultar a base Pokémon TCG.
- Opcionalmente, defina a variável POKEMONTCG_API_KEY para aumentar o limite
  de requisições da API Pokémon TCG.
"""

from __future__ import annotations

import os
import re
import sys
import time
import math
import difflib
import unicodedata
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

if MISSING:
    print("\nFaltam dependências:")
    print("  pip install " + " ".join(MISSING))
    print()
    sys.exit(1)


API_URL = "https://api.pokemontcg.io/v2/cards"
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
            "select": "id,name,number,rarity,images,set,supertype,subtypes",
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
        "ESPACO: identificar | R: limpar | Q/ESC: sair",
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
                    status = "found"

                    card = best.card
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

    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
