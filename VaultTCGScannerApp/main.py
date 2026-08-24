#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import os
import queue
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog
from typing import Callable, Optional

try:
    import customtkinter as ctk
    import cv2
    import easyocr
    import numpy as np
    import requests
    from PIL import Image
except ImportError as exc:
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Vault TCG Scanner",
        f"Dependência ausente: {exc.name}\n\n"
        "Rode instalar.bat ou:\npython -m pip install -r requirements.txt",
    )
    raise SystemExit(1)

import scanner_core as scanner

# No modo contínuo, limitar a comparação visual evita dezenas de downloads por captura.
scanner.MAX_CANDIDATES_FOR_IMAGE_COMPARE = min(scanner.MAX_CANDIDATES_FOR_IMAGE_COMPARE, 8)
from auth_service import AuthError, VaultUser, sign_in
from local_store import load_pending, save_pending
from firestore_service import FirestoreError, list_user_cards, normalize_card, save_quote
from myp_service import cotizar_carta


# ---------------------------------------------------------------------------
# Tema
# ---------------------------------------------------------------------------
BG = "#050912"
BG_SOFT = "#091220"
PANEL = "#0E1A2A"
PANEL_2 = "#13243A"
PANEL_3 = "#0A1523"
BORDER = "#263A50"
BORDER_STRONG = "#3A566F"
TEXT = "#F5F8FC"
MUTED = "#A9B8CA"
MUTED_2 = "#73849A"
ACCENT = "#54E8DF"
ACCENT_HOVER = "#39CFC8"
ACCENT_DARK = "#0D6F75"
GOLD = "#FFCB62"
ORANGE = "#FF8D4D"
SUCCESS = "#7CE5A4"
WARNING = "#FFCB62"
DANGER = "#FF6F7D"
CAMERA_BG = "#02060D"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

LANGUAGES = ["BR", "ING", "ESP", "JAP"]
CONDITIONS = ["NM", "SP", "MP", "HP", "D"]

SCAN_INTERVAL = 1.05
MAX_SCAN_WORKERS = 3
MAX_ROIS_PER_CYCLE = 3
RECENT_VISUAL_SECONDS = 5.5
MIN_CARD_AREA_RATIO = 0.055


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ellipsis(text: str, limit: int = 38) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def money(value) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except Exception:
        return "—"
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def first_present(mapping: dict, *keys, default=None):
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return value
    return default


def collector_text(record: dict) -> str:
    number = str(record.get("number") or "?")
    total = record.get("printed_total")
    return f"{number}/{total}" if total else number


def guess_language(ocr_lines: list[str]) -> tuple[str, float]:
    text = " " + scanner.normalize_text(" ".join(ocr_lines)) + " "
    pt = {
        "basico", "estagio", "fraqueza", "resistencia", "recuo", "treinador",
        "energia", "dano", "jogador", "baralho", "pokemon", "evolui", "cura",
    }
    en = {
        "basic", "stage", "weakness", "resistance", "retreat", "trainer",
        "energy", "damage", "player", "deck", "pokemon", "evolves", "heal",
    }
    pt_score = sum(1 for word in pt if f" {word} " in text)
    en_score = sum(1 for word in en if f" {word} " in text)
    if pt_score > en_score:
        return "BR", min(0.95, 0.55 + 0.09 * pt_score)
    if en_score > pt_score:
        return "ING", min(0.95, 0.55 + 0.09 * en_score)
    # O scanner original é otimizado para BR/ING; BR é o padrão do Vault.
    return "BR", 0.35


def dhash(img: np.ndarray) -> int:
    if img is None or img.size == 0:
        return 0
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    value = 0
    for bit in diff.flatten():
        value = (value << 1) | int(bit)
    return int(value)


def hamming(a: int, b: int) -> int:
    return (a ^ b).bit_count()


def order_points(pts: np.ndarray) -> np.ndarray:
    pts = np.asarray(pts, dtype="float32").reshape(4, 2)
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    diff = np.diff(pts, axis=1).reshape(-1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def warp_card(frame: np.ndarray, points: np.ndarray) -> Optional[np.ndarray]:
    try:
        rect = order_points(points)
        tl, tr, br, bl = rect
        width_a = np.linalg.norm(br - bl)
        width_b = np.linalg.norm(tr - tl)
        height_a = np.linalg.norm(tr - br)
        height_b = np.linalg.norm(tl - bl)
        max_w = max(int(width_a), int(width_b))
        max_h = max(int(height_a), int(height_b))
        if max_w < 90 or max_h < 120:
            return None
        if max_w > max_h:
            max_w, max_h = max_h, max_w
            rect = np.array([bl, tl, tr, br], dtype="float32")
        dst = np.array(
            [[0, 0], [max_w - 1, 0], [max_w - 1, max_h - 1], [0, max_h - 1]],
            dtype="float32",
        )
        matrix = cv2.getPerspectiveTransform(rect, dst)
        warped = cv2.warpPerspective(frame, matrix, (max_w, max_h))
        return warped if warped.size else None
    except Exception:
        return None


def detect_card_regions(frame: np.ndarray, max_regions: int = MAX_ROIS_PER_CYCLE) -> list[tuple[np.ndarray, np.ndarray]]:
    """Detecta até algumas cartas e devolve (ROI retificada, polígono)."""
    h, w = frame.shape[:2]
    image_area = float(h * w)
    scale = 720.0 / max(w, 1)
    if scale < 1:
        work = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    else:
        work = frame.copy()
        scale = 1.0

    gray = cv2.cvtColor(work, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(gray, 55, 145)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[tuple[float, np.ndarray]] = []
    for contour in contours:
        area = cv2.contourArea(contour) / (scale * scale)
        if area < image_area * MIN_CARD_AREA_RATIO or area > image_area * 0.76:
            continue
        peri = cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, 0.025 * peri, True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        pts = approx.reshape(4, 2).astype("float32") / scale
        rect = cv2.minAreaRect(pts.astype("float32"))
        rw, rh = rect[1]
        if min(rw, rh) <= 1:
            continue
        ratio = max(rw, rh) / min(rw, rh)
        if not (1.22 <= ratio <= 1.62):
            continue
        candidates.append((area, pts))

    candidates.sort(key=lambda item: item[0], reverse=True)
    selected: list[np.ndarray] = []
    for _, poly in candidates:
        center = poly.mean(axis=0)
        if any(np.linalg.norm(center - prev.mean(axis=0)) < min(h, w) * 0.12 for prev in selected):
            continue
        selected.append(poly)
        if len(selected) >= max(1, int(max_regions)):
            break

    found: list[tuple[np.ndarray, np.ndarray]] = []
    for poly in selected:
        roi = warp_card(frame, poly)
        if roi is not None:
            found.append((roi, poly.astype(int)))

    # Fallback: mantém a experiência simples do scanner original quando o contorno
    # não fica claro (fundo muito parecido, sleeve, reflexo etc.).
    if not found:
        roi, (x1, y1, x2, y2) = scanner.get_card_roi(frame)
        poly = np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype=int)
        found.append((roi, poly))
    return found


def identify_roi(reader: easyocr.Reader, ocr_lock: threading.Lock, card_img: np.ndarray) -> dict:
    """Pipeline do scanner original, com lock somente no OCR e rede fora dele."""
    debug = {
        "number": None,
        "total": None,
        "ocr": [],
        "candidate_count": 0,
        "myp_link": None,
        "myp": {},
        "error": None,
    }
    with ocr_lock:
        lines = scanner.run_ocr(reader, card_img)
    debug["ocr"] = [line.text for line in lines]
    number, total = scanner.extract_number(lines)
    debug["number"] = number
    debug["total"] = total
    if not number:
        debug["error"] = "Não consegui ler a numeração."
        return {"ok": False, "debug": debug}

    cards = scanner.fetch_cards_by_number(number)
    cards = scanner.filter_by_total(cards, total)
    debug["candidate_count"] = len(cards)
    if not cards:
        debug["error"] = f"Nenhuma carta encontrada para {number}."
        return {"ok": False, "debug": debug}

    ranked = scanner.rank_candidates(cards, card_img, scanner.probable_name_text(lines))
    if not ranked:
        debug["error"] = "Não consegui comparar os candidatos."
        return {"ok": False, "debug": debug}

    best = ranked[0]
    card = best.card
    myp_link, myp_info = scanner.lookup_myp_link(card)
    debug["myp_link"] = myp_link
    debug["myp"] = myp_info
    if not myp_link:
        debug["error"] = myp_info.get("error") or "Carta reconhecida, mas sem link MYP."
        return {"ok": False, "debug": debug, "candidate": card}

    set_data = card.get("set") or {}
    images = card.get("images") or {}
    lang, lang_conf = guess_language(debug["ocr"])
    record = {
        "local_id": uuid.uuid4().hex,
        "pokemon_tcg_id": card.get("id") or "",
        "name": card.get("name") or "Carta Pokémon",
        "number": card.get("number") or number,
        "printed_total": set_data.get("printedTotal") or set_data.get("total"),
        "set_name": set_data.get("name") or "Coleção não informada",
        "set_id": set_data.get("id") or "",
        "rarity": card.get("rarity") or "Não informada",
        "supertype": card.get("supertype") or "",
        "subtypes": card.get("subtypes") or [],
        "image_url": images.get("small") or images.get("large") or "",
        "image_large_url": images.get("large") or images.get("small") or "",
        "myp_link": myp_link,
        "language": lang,
        "language_confidence": round(float(lang_conf), 3),
        "condition": "NM",
        "condition_source": "estimativa inicial",
        "match_score": round(float(best.final_score), 4),
        "text_score": round(float(best.text_score), 4),
        "image_score": round(float(best.image_score), 4),
        "myp_source": myp_info.get("source"),
        "scanned_at": now_iso(),
    }
    return {"ok": True, "record": record, "debug": debug}


# ---------------------------------------------------------------------------
# Componentes simples
# ---------------------------------------------------------------------------
class AppButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("height", 44)
        kwargs.setdefault("corner_radius", 13)
        kwargs.setdefault("font", ctk.CTkFont(size=14, weight="bold"))
        kwargs.setdefault("fg_color", ACCENT)
        kwargs.setdefault("hover_color", ACCENT_HOVER)
        kwargs.setdefault("text_color", "#061017")
        super().__init__(master, **kwargs)


class GhostButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("height", 40)
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("font", ctk.CTkFont(size=13, weight="bold"))
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", PANEL_2)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", BORDER)
        kwargs.setdefault("text_color", TEXT)
        super().__init__(master, **kwargs)


class BrandMark(ctk.CTkFrame):
    def __init__(self, master, compact: bool = False):
        super().__init__(master, fg_color="transparent")
        emblem = ctk.CTkLabel(
            self, text="◇", width=42 if not compact else 36, height=42 if not compact else 36,
            corner_radius=12, fg_color="#0C1827", text_color=ACCENT,
            font=ctk.CTkFont(size=25 if not compact else 21, weight="bold"),
        )
        emblem.pack(side="left")
        copy = ctk.CTkFrame(self, fg_color="transparent")
        copy.pack(side="left", padx=(11, 0))
        ctk.CTkLabel(copy, text="VAULT TCG", text_color=TEXT, font=ctk.CTkFont(size=15 if not compact else 13, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(copy, text="SCANNER DESKTOP", text_color=MUTED_2, font=ctk.CTkFont(size=9, weight="bold")).pack(anchor="w", pady=(1, 0))


class StatChip(ctk.CTkFrame):
    def __init__(self, master, value: str, label: str, accent: str = ACCENT):
        super().__init__(master, fg_color=PANEL_2, corner_radius=14, border_width=1, border_color=BORDER)
        ctk.CTkLabel(self, text=value, text_color=accent, font=ctk.CTkFont(size=20, weight="bold")).pack(anchor="w", padx=16, pady=(11, 0))
        ctk.CTkLabel(self, text=label, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(0, 11))


class Header(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = "", back: Optional[Callable] = None, eyebrow: str = "VAULT TCG"):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        if back:
            GhostButton(self, text="←", width=44, command=back).grid(row=0, column=0, rowspan=3, padx=(0, 15), sticky="w")
        ctk.CTkLabel(self, text=eyebrow, font=ctk.CTkFont(size=10, weight="bold"), text_color=ACCENT).grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=28, weight="bold"), text_color=TEXT).grid(row=1, column=1, sticky="w", pady=(2, 0))
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=ctk.CTkFont(size=13), text_color=MUTED).grid(row=2, column=1, sticky="w", pady=(3, 0))
        line = ctk.CTkFrame(self, fg_color=BORDER, height=1)
        line.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(18, 0))


class CardDetails(ctk.CTkToplevel):
    def __init__(self, app: "VaultScannerApp", record: dict):
        super().__init__(app)
        self.app = app
        self.record = record
        self.title(record.get("name", "Carta"))
        self.geometry("720x570")
        self.minsize(650, 520)
        self.configure(fg_color=BG)
        self.transient(app)
        self.grab_set()
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=18, width=240)
        left.grid(row=0, column=0, padx=22, pady=22, sticky="nsew")
        left.grid_propagate(False)
        self.image_label = ctk.CTkLabel(left, text="Carregando imagem…", text_color=MUTED)
        self.image_label.pack(expand=True, fill="both", padx=14, pady=14)

        right = ctk.CTkFrame(self, fg_color="transparent")
        right.grid(row=0, column=1, padx=(0, 24), pady=24, sticky="nsew")
        ctk.CTkLabel(right, text=record.get("name", "Carta"), font=ctk.CTkFont(size=27, weight="bold"), text_color=TEXT).pack(anchor="w")
        ctk.CTkLabel(right, text=f"{collector_text(record)} · {record.get('set_name', '')}", font=ctk.CTkFont(size=14), text_color=MUTED).pack(anchor="w", pady=(4, 18))

        infos = [
            ("Raridade", record.get("rarity") or "—"),
            ("Idioma", record.get("language") or "—"),
            ("Estado", record.get("condition") or "—"),
            ("Confiança", f"{round(float(record.get('match_score') or 0) * 100)}%"),
            ("Fonte MYP", record.get("myp_source") or "—"),
        ]
        for label, value in infos:
            row = ctk.CTkFrame(right, fg_color=PANEL, corner_radius=10)
            row.pack(fill="x", pady=5)
            ctk.CTkLabel(row, text=label, text_color=MUTED, width=120, anchor="w").pack(side="left", padx=14, pady=10)
            ctk.CTkLabel(row, text=str(value), text_color=TEXT, anchor="w").pack(side="left", padx=(0, 14), pady=10)

        AppButton(right, text="Abrir na MYP", command=lambda: webbrowser.open(record.get("myp_link", ""))).pack(fill="x", pady=(18, 8))
        GhostButton(right, text="Fechar", command=self.destroy).pack(fill="x")
        app.load_image_async(record.get("image_large_url") or record.get("image_url"), (210, 294), self._set_image)

    def _set_image(self, image: Optional[Image.Image]):
        if not self.winfo_exists():
            return
        if image is None:
            self.image_label.configure(text="Imagem indisponível")
            return
        self._ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(210, 294))
        self.image_label.configure(image=self._ctk_image, text="")


class BaseScreen(ctk.CTkFrame):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app, fg_color=BG)
        self.app = app

    def cleanup(self):
        pass


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
class LoginScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        wrapper = ctk.CTkFrame(self, fg_color="transparent")
        wrapper.grid(row=0, column=0, padx=28, pady=28)
        BrandMark(wrapper).pack(anchor="center", pady=(0, 24))
        ctk.CTkLabel(wrapper, text="Seu acervo, agora na câmera.", font=ctk.CTkFont(size=34, weight="bold"), text_color=TEXT).pack()
        ctk.CTkLabel(wrapper, text="Entre com a mesma conta usada no site para escanear e cotizar sua coleção.", font=ctk.CTkFont(size=14), text_color=MUTED, wraplength=520).pack(pady=(8, 26))

        card = ctk.CTkFrame(wrapper, width=470, height=345, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=24)
        card.pack()
        card.pack_propagate(False)
        ctk.CTkLabel(card, text="ACESSO AO VAULT", font=ctk.CTkFont(size=10, weight="bold"), text_color=ACCENT).pack(anchor="w", padx=30, pady=(28, 3))
        ctk.CTkLabel(card, text="Entrar na conta", font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(anchor="w", padx=30, pady=(0, 14))
        self.email = ctk.CTkEntry(card, placeholder_text="E-mail", height=47, corner_radius=12, fg_color=PANEL_2, border_color=BORDER)
        self.email.pack(fill="x", padx=30, pady=6)
        self.password = ctk.CTkEntry(card, placeholder_text="Senha", show="•", height=47, corner_radius=12, fg_color=PANEL_2, border_color=BORDER)
        self.password.pack(fill="x", padx=30, pady=6)
        self.feedback = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=12), text_color=DANGER, wraplength=400)
        self.feedback.pack(fill="x", padx=30, pady=(2, 2))
        self.login_btn = AppButton(card, text="Entrar no Vault", command=self._login)
        self.login_btn.pack(fill="x", padx=30, pady=(7, 26))
        self.password.bind("<Return>", lambda _: self._login())

    def _login(self):
        email = self.email.get().strip()
        password = self.password.get()
        self.feedback.configure(text="Conectando à sua conta…", text_color=MUTED)
        self.login_btn.configure(state="disabled", text="Entrando…")

        def worker():
            try:
                user = sign_in(email, password)
            except AuthError as exc:
                message = str(exc)
                self.app.post_ui(lambda m=message: self._login_failed(m))
            except Exception:
                self.app.post_ui(lambda: self._login_failed("Não foi possível entrar agora."))
            else:
                self.app.post_ui(lambda: self._login_ok(user))

        threading.Thread(target=worker, daemon=True).start()

    def _login_failed(self, message: str):
        if not self.winfo_exists():
            return
        self.feedback.configure(text=message, text_color=DANGER)
        self.login_btn.configure(state="normal", text="Entrar no Vault")

    def _login_ok(self, user: VaultUser):
        self.app.user = user
        self.app.pending_cards = load_pending(user.uid)
        self.password.delete(0, "end")
        self.app.show_home()


class HomeScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="#07101D", border_width=0)
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(1, weight=1)
        BrandMark(top, compact=True).grid(row=0, column=0, padx=40, pady=18, sticky="w")
        user_box = ctk.CTkFrame(top, fg_color="transparent")
        user_box.grid(row=0, column=1, padx=(0, 14), sticky="e")
        ctk.CTkLabel(user_box, text="CONECTADO", text_color=SUCCESS, font=ctk.CTkFont(size=9, weight="bold")).pack(anchor="e")
        ctk.CTkLabel(user_box, text=app.user.email if app.user else "", text_color=MUTED, font=ctk.CTkFont(size=12)).pack(anchor="e")
        GhostButton(top, text="Sair", width=82, command=app.logout).grid(row=0, column=2, padx=(0, 40), pady=18)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, padx=42, pady=(34, 38), sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        body.grid_rowconfigure(2, weight=1)

        hero = ctk.CTkFrame(body, fg_color="transparent")
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 20))
        ctk.CTkLabel(hero, text="FERRAMENTAS DO COLECIONADOR", text_color=ACCENT, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(hero, text="Scanner & cotização do seu Vault", text_color=TEXT, font=ctk.CTkFont(size=32, weight="bold")).pack(anchor="w", pady=(4, 5))
        ctk.CTkLabel(hero, text="Reconheça cartas pela câmera ou por fotos e atualize preços direto da MYP.", text_color=MUTED, font=ctk.CTkFont(size=14)).pack(anchor="w")

        pending_count = len(app.pending_cards)
        stats = ctk.CTkFrame(body, fg_color="transparent")
        stats.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        stats.grid_columnconfigure((0, 1, 2), weight=1)
        StatChip(stats, str(pending_count), "cartas na fila local", ACCENT).grid(row=0, column=0, padx=(0, 7), sticky="ew")
        StatChip(stats, "2", "formas de escanear", GOLD).grid(row=0, column=1, padx=7, sticky="ew")
        StatChip(stats, "MYP", "fonte de cotização", SUCCESS).grid(row=0, column=2, padx=(7, 0), sticky="ew")

        register = self._action_card(body, "⌁", "REGISTRO", "Registrar novas cartas", "Câmera contínua ou importação de fotos. O app reconhece a carta e encontra o produto na MYP.", "Abrir scanner", app.show_register_methods, ACCENT)
        register.grid(row=2, column=0, padx=(0, 10), sticky="nsew")

        quote = self._action_card(body, "↻", "COTIZAÇÃO", "Cotizar minha coleção", "Carrega suas cartas do Firestore, consulta cada link MYP e mostra a variação antes de salvar no Vault.", "Nova cotização", app.show_quote, GOLD)
        quote.grid(row=2, column=1, padx=(10, 0), sticky="nsew")

        pending = ctk.CTkFrame(body, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=18)
        pending.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(20, 0))
        pending.grid_columnconfigure(1, weight=1)
        badge = ctk.CTkLabel(pending, text=str(pending_count), width=48, height=48, corner_radius=14, fg_color=PANEL_2, text_color=ACCENT, font=ctk.CTkFont(size=20, weight="bold"))
        badge.grid(row=0, column=0, rowspan=2, padx=18, pady=15)
        ctk.CTkLabel(pending, text="Fila local de registro", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(pending, text="Revise idioma e estado antes da futura sincronização final de cadastro.", text_color=MUTED).grid(row=1, column=1, sticky="nw", pady=(2, 0))
        GhostButton(pending, text="Ver fila", width=110, command=app.show_pending, state="normal" if pending_count else "disabled").grid(row=0, column=2, rowspan=2, padx=18)

    def _action_card(self, master, icon, eyebrow, title, desc, button_text, command, accent):
        frame = ctk.CTkFrame(master, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=24)
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=24, pady=(25, 10))
        ctk.CTkLabel(top, text=icon, width=50, height=50, corner_radius=16, fg_color=PANEL_2, text_color=accent, font=ctk.CTkFont(size=26, weight="bold")).pack(side="left")
        copy = ctk.CTkFrame(top, fg_color="transparent")
        copy.pack(side="left", padx=(15, 0), fill="x", expand=True)
        ctk.CTkLabel(copy, text=eyebrow, font=ctk.CTkFont(size=10, weight="bold"), text_color=accent).pack(anchor="w")
        ctk.CTkLabel(copy, text=title, font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(frame, text=desc, font=ctk.CTkFont(size=14), text_color=MUTED, wraplength=440, justify="left").pack(anchor="w", padx=24)
        AppButton(frame, text=button_text, command=command, fg_color=accent, hover_color=ACCENT_HOVER if accent == ACCENT else "#E7B64E").pack(fill="x", side="bottom", padx=24, pady=24)
        return frame


class RegisterMethodsScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        Header(self, "Registrar novas cartas", "Escolha como as imagens serão capturadas e analisadas.", back=app.show_home, eyebrow="SCANNER").grid(row=0, column=0, padx=42, pady=(30, 20), sticky="ew")

        methods = ctk.CTkFrame(self, fg_color="transparent")
        methods.grid(row=1, column=0, padx=42, pady=(6, 42), sticky="nsew")
        methods.grid_columnconfigure((0, 1), weight=1, uniform="m")
        methods.grid_rowconfigure(0, weight=1)
        self._method_card(methods, 0, "◉", "CÂMERA", "Scanner contínuo", "A câmera fica procurando cartas automaticamente. Ideal para registrar várias cartas em sequência sem apertar um botão a cada leitura.", "Abrir câmera", app.show_camera, ACCENT, (0, 10))
        self._method_card(methods, 1, "▧", "FOTO", "Importar imagens", "Escolha uma ou várias fotos do computador. Cada imagem é analisada, as cartas são recortadas e identificadas pelo mesmo motor do scanner.", "Selecionar fotos", app.show_photo, GOLD, (10, 0))

    def _method_card(self, master, column, icon, eyebrow, title, desc, button, command, accent, padx):
        card = ctk.CTkFrame(master, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=24)
        card.grid(row=0, column=column, padx=padx, sticky="nsew")
        ctk.CTkLabel(card, text=icon, width=62, height=62, corner_radius=18, fg_color=PANEL_2, text_color=accent, font=ctk.CTkFont(size=31)).pack(anchor="w", padx=26, pady=(28, 18))
        ctk.CTkLabel(card, text=eyebrow, font=ctk.CTkFont(size=10, weight="bold"), text_color=accent).pack(anchor="w", padx=26)
        ctk.CTkLabel(card, text=title, font=ctk.CTkFont(size=25, weight="bold"), text_color=TEXT).pack(anchor="w", padx=26, pady=(3, 8))
        ctk.CTkLabel(card, text=desc, wraplength=440, justify="left", text_color=MUTED, font=ctk.CTkFont(size=14)).pack(anchor="w", padx=26)
        AppButton(card, text=button, command=command, fg_color=accent, hover_color=ACCENT_HOVER if accent == ACCENT else "#E7B64E").pack(fill="x", padx=26, pady=26, side="bottom")


# ---------------------------------------------------------------------------
# Scanner por foto
# ---------------------------------------------------------------------------
class PhotoScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.active = True
        self.files: list[str] = []
        self.found_cards: list[dict] = []
        self.found_ids: set[str] = set()
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="vault-photo")
        self.active_jobs = 0
        self.total_jobs = 0
        self.completed_jobs = 0

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)
        Header(self, "Scanner por foto", "Importe uma ou várias imagens; a análise usa o mesmo OCR e reconhecimento da câmera.", back=self._go_back, eyebrow="SCANNER").grid(row=0, column=0, columnspan=2, padx=28, pady=(22, 14), sticky="ew")

        left = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=20, border_width=1, border_color=BORDER)
        left.grid(row=1, column=0, padx=(28, 10), pady=(0, 24), sticky="nsew")
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(1, weight=1)

        toolbar = ctk.CTkFrame(left, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=18, pady=18, sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        title_box = ctk.CTkFrame(toolbar, fg_color="transparent")
        title_box.grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(title_box, text="IMAGENS DE ENTRADA", text_color=ACCENT, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(title_box, text="Fotos para analisar", text_color=TEXT, font=ctk.CTkFont(size=19, weight="bold")).pack(anchor="w")
        AppButton(toolbar, text="+ Selecionar fotos", width=155, command=self._choose_files).grid(row=0, column=1, sticky="e")

        preview = ctk.CTkFrame(left, fg_color=CAMERA_BG, corner_radius=16, border_width=1, border_color=BORDER)
        preview.grid(row=1, column=0, padx=18, pady=(0, 12), sticky="nsew")
        preview.grid_columnconfigure(0, weight=1)
        preview.grid_rowconfigure(0, weight=1)
        self.preview_label = ctk.CTkLabel(preview, text="Selecione JPG, PNG ou WEBP\npara começar.", text_color=MUTED, justify="center")
        self.preview_label.grid(row=0, column=0, padx=12, pady=12, sticky="nsew")

        self.file_label = ctk.CTkLabel(left, text="Nenhuma foto selecionada", text_color=MUTED, anchor="w")
        self.file_label.grid(row=2, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.progress = ctk.CTkProgressBar(left, height=8, corner_radius=99, progress_color=ACCENT, fg_color=PANEL_2)
        self.progress.grid(row=3, column=0, padx=18, pady=(0, 8), sticky="ew")
        self.progress.set(0)
        self.status_label = ctk.CTkLabel(left, text="Pronto para importar.", text_color=MUTED, anchor="w")
        self.status_label.grid(row=4, column=0, padx=18, pady=(0, 18), sticky="ew")

        right = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=20, border_width=1, border_color=BORDER)
        right.grid(row=1, column=1, padx=(10, 28), pady=(0, 24), sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)
        header = ctk.CTkFrame(right, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(17, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Cartas localizadas", font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.count_badge = ctk.CTkLabel(header, text="0", width=34, height=28, corner_radius=8, fg_color=PANEL_2, text_color=ACCENT)
        self.count_badge.grid(row=0, column=1)
        self.cards_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.cards_scroll.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        self.cards_scroll.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.cards_scroll, text="As cartas reconhecidas nas fotos\naparecerão aqui.", text_color=MUTED, justify="center", wraplength=310)
        self.empty_label.grid(row=0, column=0, padx=20, pady=50)
        self.rescue_btn = AppButton(right, text="Revisar cartas", command=self._rescue, state="disabled")
        self.rescue_btn.grid(row=2, column=0, padx=16, pady=16, sticky="ew")

    def _choose_files(self):
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Escolher fotos de cartas Pokémon",
            filetypes=[("Imagens", "*.jpg *.jpeg *.png *.webp *.bmp"), ("Todos os arquivos", "*.*")],
        )
        if not paths:
            return
        self.files = list(paths)
        self.file_label.configure(text=f"{len(self.files)} foto" + ("s" if len(self.files) != 1 else "") + " selecionada" + ("s" if len(self.files) != 1 else ""))
        self._show_preview(self.files[0])
        self._ensure_ocr_then_start()

    def _show_preview(self, path: str):
        try:
            image = Image.open(path).convert("RGB")
            box_w = max(620, self.winfo_width() // 2)
            box_h = max(410, self.winfo_height() - 270)
            image.thumbnail((box_w, box_h), Image.Resampling.LANCZOS)
            self._preview_ctk = ctk.CTkImage(light_image=image, dark_image=image, size=image.size)
            self.preview_label.configure(image=self._preview_ctk, text="")
        except Exception:
            self.preview_label.configure(image=None, text="Não foi possível abrir a prévia desta imagem.")

    def _ensure_ocr_then_start(self):
        if self.app.ocr_reader is not None:
            self._start_processing()
            return
        self.status_label.configure(text="Carregando OCR pela primeira vez…", text_color=WARNING)

        def load():
            try:
                try:
                    reader = easyocr.Reader(["pt", "en"], gpu=False)
                except Exception:
                    reader = easyocr.Reader(["en"], gpu=False)
            except Exception as exc:
                self.app.post_ui(lambda m=str(exc): self.status_label.configure(text=f"Falha no OCR: {ellipsis(m, 75)}", text_color=DANGER))
                return
            self.app.ocr_reader = reader
            self.app.post_ui(self._start_processing)

        threading.Thread(target=load, daemon=True, name="vault-photo-ocr-loader").start()

    def _start_processing(self):
        if not self.active or not self.files:
            return
        self.total_jobs = len(self.files)
        self.completed_jobs = 0
        self.active_jobs = len(self.files)
        self.progress.set(0)
        self.status_label.configure(text=f"Analisando {len(self.files)} foto" + ("s" if len(self.files) != 1 else "") + "…", text_color=WARNING)
        for path in self.files:
            future = self.executor.submit(self._process_file, path)
            future.add_done_callback(lambda fut, p=path: self.app.post_ui(lambda f=fut, path=p: self._photo_finished(path, f)))

    def _process_file(self, path: str) -> list[dict]:
        raw = np.fromfile(path, dtype=np.uint8)
        frame = cv2.imdecode(raw, cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError("Imagem inválida ou formato não suportado.")
        regions = detect_card_regions(frame, max_regions=8)
        results = []
        for roi, _ in regions[:8]:
            result = identify_roi(self.app.ocr_reader, self.app.ocr_lock, roi)
            if result.get("ok"):
                results.append(result["record"])
        return results

    def _photo_finished(self, path: str, future):
        if not self.active or not self.winfo_exists():
            return
        self.completed_jobs += 1
        self.active_jobs = max(0, self.active_jobs - 1)
        try:
            records = future.result()
        except Exception as exc:
            records = []
            self.status_label.configure(text=f"Falha em {Path(path).name}: {ellipsis(str(exc), 65)}", text_color=DANGER)
        for record in records:
            unique = record.get("pokemon_tcg_id") or record.get("myp_link")
            if unique and unique in self.found_ids:
                continue
            if unique:
                self.found_ids.add(unique)
            self.found_cards.append(record)
            self._add_card_tile(record)
        self.count_badge.configure(text=str(len(self.found_cards)))
        self.progress.set(self.completed_jobs / max(1, self.total_jobs))
        if self.found_cards:
            self.rescue_btn.configure(state="normal", text=f"Revisar {len(self.found_cards)} carta" + ("s" if len(self.found_cards) != 1 else ""))
        if self.completed_jobs >= self.total_jobs:
            self.status_label.configure(text=f"Análise concluída · {len(self.found_cards)} carta" + ("s" if len(self.found_cards) != 1 else "") + " localizada" + ("s" if len(self.found_cards) != 1 else ""), text_color=SUCCESS if self.found_cards else WARNING)
        elif records:
            self.status_label.configure(text=f"{self.completed_jobs}/{self.total_jobs} fotos analisadas · {len(self.found_cards)} cartas encontradas", text_color=WARNING)

    def _add_card_tile(self, record: dict):
        if self.empty_label.winfo_exists():
            self.empty_label.destroy()
        tile = ctk.CTkFrame(self.cards_scroll, fg_color=PANEL_2, corner_radius=12, border_width=1, border_color=BORDER)
        tile.grid(row=len(self.found_cards), column=0, padx=2, pady=6, sticky="ew")
        tile.grid_columnconfigure(1, weight=1)
        image_label = ctk.CTkLabel(tile, text="…", width=58, height=80, text_color=MUTED)
        image_label.grid(row=0, column=0, rowspan=2, padx=10, pady=9)
        ctk.CTkLabel(tile, text=ellipsis(record.get("name"), 27), font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT, anchor="w").grid(row=0, column=1, sticky="sw", padx=(0, 8), pady=(12, 0))
        ctk.CTkLabel(tile, text=f"{collector_text(record)} · {ellipsis(record.get('set_name'), 22)}", text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="nw", padx=(0, 8), pady=(2, 12))
        GhostButton(tile, text="Ver", width=54, command=lambda r=record: CardDetails(self.app, r)).grid(row=0, column=2, rowspan=2, padx=(0, 10))

        def set_thumb(image):
            if not tile.winfo_exists():
                return
            if image is None:
                image_label.configure(text="?")
                return
            thumb = ctk.CTkImage(light_image=image, dark_image=image, size=(52, 73))
            image_label._vault_image = thumb
            image_label.configure(image=thumb, text="")
        self.app.load_image_async(record.get("image_url"), (52, 73), set_thumb)

    def _rescue(self):
        if not self.found_cards:
            return
        batch = [dict(card) for card in self.found_cards]
        self.cleanup()
        self.app.show_review(batch)

    def _go_back(self):
        self.cleanup()
        self.app.show_register_methods()

    def cleanup(self):
        if not self.active:
            return
        self.active = False
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Câmera
# ---------------------------------------------------------------------------
class CameraScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.active = True
        self.cap: Optional[cv2.VideoCapture] = None
        self.executor = ThreadPoolExecutor(max_workers=MAX_SCAN_WORKERS, thread_name_prefix="vault-scan")
        self.ocr_lock = app.ocr_lock
        self.active_jobs = 0
        self.last_scan_at = 0.0
        self.recent_visuals: list[tuple[int, float]] = []
        self.found_ids: set[str] = set()
        self.found_cards: list[dict] = []
        self.last_polys: list[np.ndarray] = []
        self.frame_count = 0

        self.grid_columnconfigure(0, weight=3)
        self.grid_columnconfigure(1, weight=2)
        self.grid_rowconfigure(1, weight=1)

        Header(self, "Scanner por câmera", "A leitura é automática. Você pode mostrar cartas diferentes em sequência.", back=self._go_back).grid(row=0, column=0, columnspan=2, padx=28, pady=(22, 14), sticky="ew")

        self.camera_panel = ctk.CTkFrame(self, fg_color=CAMERA_BG, corner_radius=18, border_width=1, border_color=BORDER)
        self.camera_panel.grid(row=1, column=0, padx=(28, 10), pady=(0, 22), sticky="nsew")
        self.camera_panel.grid_rowconfigure(0, weight=1)
        self.camera_panel.grid_columnconfigure(0, weight=1)
        self.video_label = ctk.CTkLabel(self.camera_panel, text="Abrindo câmera…", text_color=MUTED)
        self.video_label.grid(row=0, column=0, padx=8, pady=8, sticky="nsew")
        self.status_label = ctk.CTkLabel(self.camera_panel, text="Inicializando…", fg_color="#101725", corner_radius=9, text_color=TEXT, height=32)
        self.status_label.grid(row=1, column=0, padx=12, pady=(0, 12), sticky="ew")

        right = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=18, border_width=1, border_color=BORDER)
        right.grid(row=1, column=1, padx=(10, 28), pady=(0, 22), sticky="nsew")
        right.grid_rowconfigure(1, weight=1)
        right.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(right, fg_color="transparent")
        header.grid(row=0, column=0, padx=16, pady=(16, 8), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="Cartas localizadas", font=ctk.CTkFont(size=18, weight="bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        self.count_badge = ctk.CTkLabel(header, text="0", width=34, height=28, corner_radius=8, fg_color=PANEL_2, text_color=ACCENT)
        self.count_badge.grid(row=0, column=1)

        self.cards_scroll = ctk.CTkScrollableFrame(right, fg_color="transparent")
        self.cards_scroll.grid(row=1, column=0, padx=10, pady=4, sticky="nsew")
        self.cards_scroll.grid_columnconfigure(0, weight=1)
        self.empty_label = ctk.CTkLabel(self.cards_scroll, text="Mostre uma carta para a câmera.\nEla aparecerá aqui assim que for localizada na MYP.", text_color=MUTED, justify="center", wraplength=310)
        self.empty_label.grid(row=0, column=0, padx=20, pady=50)

        self.rescue_btn = AppButton(right, text="Resgatar cartas", command=self._rescue, state="disabled")
        self.rescue_btn.grid(row=2, column=0, padx=16, pady=16, sticky="ew")

        self._open_camera()
        self._ensure_ocr()

    def _open_camera(self):
        self.cap = scanner.open_camera(0)
        if not self.cap or not self.cap.isOpened():
            self.status_label.configure(text="Não foi possível abrir a câmera.", text_color=DANGER)
            return
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        self.after(20, self._update_video)

    def _ensure_ocr(self):
        if self.app.ocr_reader is not None:
            self.status_label.configure(text="Câmera ativa · procurando cartas automaticamente", text_color=SUCCESS)
            return
        self.status_label.configure(text="Carregando OCR pela primeira vez…", text_color=WARNING)

        def load():
            try:
                try:
                    reader = easyocr.Reader(["pt", "en"], gpu=False)
                except Exception:
                    reader = easyocr.Reader(["en"], gpu=False)
            except Exception as exc:
                message = str(exc)
                self.app.post_ui(lambda m=message: self._ocr_failed(m))
                return
            self.app.ocr_reader = reader
            self.app.post_ui(self._ocr_ready)

        threading.Thread(target=load, daemon=True, name="vault-ocr-loader").start()

    def _ocr_ready(self):
        if self.active and self.winfo_exists():
            self.status_label.configure(text="Câmera ativa · procurando cartas automaticamente", text_color=SUCCESS)

    def _ocr_failed(self, message: str):
        if self.active and self.winfo_exists():
            self.status_label.configure(text=f"Falha ao carregar OCR: {ellipsis(message, 75)}", text_color=DANGER)

    def _update_video(self):
        if not self.active or not self.cap or not self.cap.isOpened():
            return
        ok, frame = self.cap.read()
        if not ok or frame is None:
            self.status_label.configure(text="Falha ao ler a câmera.", text_color=DANGER)
            return
        frame = cv2.flip(frame, 1)
        self.frame_count += 1

        # Detecção geométrica para desenhar molduras; a cada poucos frames basta.
        if self.frame_count % 5 == 0:
            try:
                regions = detect_card_regions(frame)
                self.last_polys = [poly for _, poly in regions]
            except Exception:
                self.last_polys = []

        shown = frame.copy()
        for poly in self.last_polys:
            cv2.polylines(shown, [poly.astype(np.int32)], True, (223, 232, 84), 3, cv2.LINE_AA)
        cv2.putText(shown, "DETECCAO AUTOMATICA", (18, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (245, 245, 250), 2, cv2.LINE_AA)

        rgb = cv2.cvtColor(shown, cv2.COLOR_BGR2RGB)
        pil = Image.fromarray(rgb)
        box_w = max(640, self.camera_panel.winfo_width() - 18)
        box_h = max(420, self.camera_panel.winfo_height() - 65)
        pil.thumbnail((box_w, box_h), Image.Resampling.LANCZOS)
        self._video_ctk = ctk.CTkImage(light_image=pil, dark_image=pil, size=pil.size)
        self.video_label.configure(image=self._video_ctk, text="")

        now = time.monotonic()
        if self.app.ocr_reader is not None and self.active_jobs < MAX_SCAN_WORKERS and now - self.last_scan_at >= SCAN_INTERVAL:
            self.last_scan_at = now
            try:
                regions = detect_card_regions(frame)
                self._submit_regions(regions)
            except Exception:
                pass

        self.after(28, self._update_video)

    def _submit_regions(self, regions: list[tuple[np.ndarray, np.ndarray]]):
        now = time.monotonic()
        self.recent_visuals = [(sig, ts) for sig, ts in self.recent_visuals if now - ts < RECENT_VISUAL_SECONDS]
        for roi, _ in regions[:MAX_ROIS_PER_CYCLE]:
            if self.active_jobs >= MAX_SCAN_WORKERS:
                break
            sig = dhash(roi)
            if any(hamming(sig, old_sig) <= 7 for old_sig, _ in self.recent_visuals):
                continue
            self.recent_visuals.append((sig, now))
            self.active_jobs += 1
            self._refresh_status()
            future = self.executor.submit(identify_roi, self.app.ocr_reader, self.ocr_lock, roi.copy())
            future.add_done_callback(lambda fut: self.app.post_ui(lambda f=fut: self._scan_finished(f)))

    def _scan_finished(self, future):
        self.active_jobs = max(0, self.active_jobs - 1)
        if not self.active or not self.winfo_exists():
            return
        try:
            result = future.result()
        except Exception as exc:
            self._refresh_status(ellipsis(str(exc), 75))
            return
        if not result.get("ok"):
            # Falhas de leitura são normais no scanner contínuo; não poluem a lista.
            self._refresh_status()
            return
        record = result["record"]
        unique = record.get("pokemon_tcg_id") or record.get("myp_link")
        if unique in self.found_ids:
            self._refresh_status()
            return
        self.found_ids.add(unique)
        self.found_cards.append(record)
        self._add_card_tile(record)
        self.count_badge.configure(text=str(len(self.found_cards)))
        self.rescue_btn.configure(state="normal", text=f"Resgatar {len(self.found_cards)} carta" + ("s" if len(self.found_cards) != 1 else ""))
        self._refresh_status(f"Encontrada: {record.get('name')} · MYP localizado", success=True)

    def _refresh_status(self, custom: str = "", success: bool = False):
        if not self.active or not self.winfo_exists():
            return
        if custom:
            self.status_label.configure(text=custom, text_color=SUCCESS if success else MUTED)
        elif self.active_jobs:
            self.status_label.configure(text=f"Analisando {self.active_jobs} captura" + ("s" if self.active_jobs != 1 else "") + " em paralelo…", text_color=WARNING)
        else:
            self.status_label.configure(text="Câmera ativa · procurando cartas automaticamente", text_color=SUCCESS)

    def _add_card_tile(self, record: dict):
        if self.empty_label.winfo_exists():
            self.empty_label.destroy()
        tile = ctk.CTkFrame(self.cards_scroll, fg_color=PANEL_2, corner_radius=12, border_width=1, border_color=BORDER)
        tile.grid(row=len(self.found_cards), column=0, padx=2, pady=6, sticky="ew")
        tile.grid_columnconfigure(1, weight=1)
        image_label = ctk.CTkLabel(tile, text="…", width=58, height=80, text_color=MUTED)
        image_label.grid(row=0, column=0, rowspan=2, padx=10, pady=9)
        name = ctk.CTkLabel(tile, text=ellipsis(record.get("name"), 27), font=ctk.CTkFont(size=14, weight="bold"), text_color=TEXT, anchor="w")
        name.grid(row=0, column=1, sticky="sw", padx=(0, 8), pady=(12, 0))
        meta = ctk.CTkLabel(tile, text=f"{collector_text(record)} · {ellipsis(record.get('set_name'), 24)}", text_color=MUTED, anchor="w")
        meta.grid(row=1, column=1, sticky="nw", padx=(0, 8), pady=(2, 12))
        GhostButton(tile, text="Ver", width=54, command=lambda r=record: CardDetails(self.app, r)).grid(row=0, column=2, rowspan=2, padx=(0, 10))

        def set_thumb(image):
            if not tile.winfo_exists():
                return
            if image is None:
                image_label.configure(text="?")
                return
            thumb = ctk.CTkImage(light_image=image, dark_image=image, size=(52, 73))
            image_label._vault_image = thumb
            image_label.configure(image=thumb, text="")

        self.app.load_image_async(record.get("image_url"), (52, 73), set_thumb)

    def _rescue(self):
        if not self.found_cards:
            return
        batch = [dict(card) for card in self.found_cards]
        self.cleanup()
        self.app.show_review(batch)

    def _go_back(self):
        self.cleanup()
        self.app.show_register_methods()

    def cleanup(self):
        if not self.active:
            return
        self.active = False
        if self.cap:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Cotização MYP da coleção do usuário
# ---------------------------------------------------------------------------
class QuoteScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.active = True
        self.cards: list[dict] = []
        self.filtered_cards: list[dict] = []
        self.check_vars: dict[str, ctk.BooleanVar] = {}
        self.row_widgets: dict[str, dict[str, object]] = {}
        self.results: dict[str, dict] = {}
        self.failed: dict[str, str] = {}
        self.quote_executor: Optional[ThreadPoolExecutor] = None
        self.total_quote_jobs = 0
        self.completed_quote_jobs = 0
        self.saving = False

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        Header(self, "Cotização da coleção", "Carrega suas cartas do Vault e consulta a MYP diretamente deste computador.", back=self._go_back, eyebrow="MYP · FIRESTORE").grid(row=0, column=0, padx=30, pady=(22, 12), sticky="ew")

        summary = ctk.CTkFrame(self, fg_color="transparent")
        summary.grid(row=1, column=0, padx=30, pady=(0, 12), sticky="ew")
        summary.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.stat_loaded = StatChip(summary, "…", "cartas carregadas", ACCENT)
        self.stat_loaded.grid(row=0, column=0, padx=(0, 6), sticky="ew")
        self.stat_selected = StatChip(summary, "0", "selecionadas", GOLD)
        self.stat_selected.grid(row=0, column=1, padx=6, sticky="ew")
        self.stat_quoted = StatChip(summary, "0", "cotizadas", SUCCESS)
        self.stat_quoted.grid(row=0, column=2, padx=6, sticky="ew")
        self.stat_value = StatChip(summary, "—", "valor cotado selecionado", GOLD)
        self.stat_value.grid(row=0, column=3, padx=(6, 0), sticky="ew")

        panel = ctk.CTkFrame(self, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=20)
        panel.grid(row=2, column=0, padx=30, pady=(0, 16), sticky="nsew")
        panel.grid_columnconfigure(0, weight=1)
        panel.grid_rowconfigure(2, weight=1)

        toolbar = ctk.CTkFrame(panel, fg_color="transparent")
        toolbar.grid(row=0, column=0, padx=16, pady=(16, 10), sticky="ew")
        toolbar.grid_columnconfigure(0, weight=1)
        self.search = ctk.CTkEntry(toolbar, placeholder_text="Buscar por nome, número ou coleção…", height=42, corner_radius=12, fg_color=PANEL_2, border_color=BORDER)
        self.search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.search.bind("<KeyRelease>", lambda _: self._apply_filter())
        GhostButton(toolbar, text="Selecionar com MYP", width=150, command=self._select_all_with_link).grid(row=0, column=1, padx=4)
        GhostButton(toolbar, text="Limpar", width=82, command=self._clear_selection).grid(row=0, column=2, padx=(4, 0))

        self.notice = ctk.CTkLabel(panel, text="Carregando sua coleção do Firestore…", text_color=MUTED, anchor="w")
        self.notice.grid(row=1, column=0, padx=18, pady=(0, 6), sticky="ew")

        self.scroll = ctk.CTkScrollableFrame(panel, fg_color="transparent")
        self.scroll.grid(row=2, column=0, padx=10, pady=(0, 10), sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.scroll, text="Buscando cartas…", text_color=MUTED).grid(row=0, column=0, pady=60)

        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, padx=30, pady=(0, 24), sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        progress_box = ctk.CTkFrame(bottom, fg_color="transparent")
        progress_box.grid(row=0, column=0, sticky="ew", padx=(0, 14))
        progress_box.grid_columnconfigure(0, weight=1)
        self.progress_label = ctk.CTkLabel(progress_box, text="Selecione as cartas que deseja cotizar.", text_color=MUTED, anchor="w")
        self.progress_label.grid(row=0, column=0, sticky="ew")
        self.progress = ctk.CTkProgressBar(progress_box, height=8, corner_radius=99, progress_color=ACCENT, fg_color=PANEL_2)
        self.progress.grid(row=1, column=0, sticky="ew", pady=(7, 0))
        self.progress.set(0)
        self.save_btn = GhostButton(bottom, text="Salvar cotações no Vault", width=190, state="disabled", command=self._save_results)
        self.save_btn.grid(row=0, column=1, padx=(0, 8))
        self.quote_btn = AppButton(bottom, text="Cotizar selecionadas", width=180, state="disabled", command=self._start_quote)
        self.quote_btn.grid(row=0, column=2)

        threading.Thread(target=self._load_cards_worker, daemon=True, name="vault-firestore-load").start()

    def _load_cards_worker(self):
        try:
            raw_cards = list_user_cards(self.app.user)
            cards = [normalize_card(card) for card in raw_cards]
        except Exception as exc:
            self.app.post_ui(lambda m=str(exc): self._load_failed(m))
            return
        self.app.post_ui(lambda: self._load_ok(cards))

    def _load_failed(self, message: str):
        if not self.active or not self.winfo_exists():
            return
        self.notice.configure(text=message or "Não foi possível carregar sua coleção.", text_color=DANGER)
        for child in self.scroll.winfo_children():
            child.destroy()
        ctk.CTkLabel(self.scroll, text="Falha ao carregar as cartas do Vault.", text_color=DANGER).grid(row=0, column=0, pady=60)

    def _load_ok(self, cards: list[dict]):
        if not self.active or not self.winfo_exists():
            return
        self.cards = cards
        with_link = sum(1 for card in cards if card.get("linkMyp"))
        self.stat_loaded.winfo_children()[0].configure(text=str(len(cards)))
        self.notice.configure(text=f"{len(cards)} cartas carregadas · {with_link} com link MYP · {len(cards) - with_link} sem link MYP", text_color=MUTED)
        self._apply_filter()
        self._update_summary()

    def _apply_filter(self):
        term = self.search.get().strip().lower() if self.search.winfo_exists() else ""
        if not term:
            self.filtered_cards = list(self.cards)
        else:
            self.filtered_cards = [
                card for card in self.cards
                if term in f"{card.get('name','')} {card.get('number','')} {card.get('collection','')}".lower()
            ]
        self._render_rows()

    def _render_rows(self):
        for child in self.scroll.winfo_children():
            child.destroy()
        self.row_widgets.clear()
        if not self.filtered_cards:
            ctk.CTkLabel(self.scroll, text="Nenhuma carta encontrada neste filtro.", text_color=MUTED).grid(row=0, column=0, pady=60)
            return
        for index, card in enumerate(self.filtered_cards):
            doc_id = str(card.get("_doc_id") or index)
            var = self.check_vars.get(doc_id)
            if var is None:
                var = ctk.BooleanVar(value=False)
                self.check_vars[doc_id] = var
            row = ctk.CTkFrame(self.scroll, fg_color=PANEL_2, border_width=1, border_color=BORDER, corner_radius=14)
            row.grid(row=index, column=0, padx=2, pady=5, sticky="ew")
            row.grid_columnconfigure(2, weight=1)
            checkbox = ctk.CTkCheckBox(row, text="", width=28, variable=var, command=self._update_summary, fg_color=ACCENT, hover_color=ACCENT_HOVER, border_color=BORDER_STRONG)
            checkbox.grid(row=0, column=0, rowspan=2, padx=(12, 5), pady=12)
            if not card.get("linkMyp"):
                checkbox.configure(state="disabled")
            image_label = ctk.CTkLabel(row, text="", width=48, height=67, corner_radius=8, fg_color=PANEL_3)
            image_label.grid(row=0, column=1, rowspan=2, padx=(0, 12), pady=9)
            ctk.CTkLabel(row, text=ellipsis(card.get("name"), 36), text_color=TEXT, font=ctk.CTkFont(size=14, weight="bold"), anchor="w").grid(row=0, column=2, sticky="sw", pady=(10, 0))
            meta = f"{card.get('number') or 's/n'} · {ellipsis(card.get('collection'), 26)} · {card.get('condition') or '—'} · x{card.get('quantity', 1)}"
            ctk.CTkLabel(row, text=meta, text_color=MUTED, anchor="w", font=ctk.CTkFont(size=11)).grid(row=1, column=2, sticky="nw", pady=(2, 10))
            old = self._current_unit_value(card)
            price = ctk.CTkLabel(row, text=money(old), text_color=GOLD if old is not None else MUTED, width=105, anchor="e", font=ctk.CTkFont(size=13, weight="bold"))
            price.grid(row=0, column=3, sticky="se", padx=(8, 12), pady=(10, 0))
            status_text = "pronta" if card.get("linkMyp") else "sem link MYP"
            status_color = MUTED if card.get("linkMyp") else DANGER
            status = ctk.CTkLabel(row, text=status_text, text_color=status_color, width=105, anchor="e", font=ctk.CTkFont(size=10))
            status.grid(row=1, column=3, sticky="ne", padx=(8, 12), pady=(1, 10))
            self.row_widgets[doc_id] = {"row": row, "price": price, "status": status}
            result = self.results.get(doc_id)
            if result:
                self._apply_result_to_row(doc_id, result)
            elif doc_id in self.failed:
                status.configure(text="falhou", text_color=DANGER)

            image_url = card.get("image")
            if image_url:
                def set_thumb(image, label=image_label):
                    if not label.winfo_exists():
                        return
                    if image is None:
                        return
                    thumb = ctk.CTkImage(light_image=image, dark_image=image, size=(44, 62))
                    label._vault_image = thumb
                    label.configure(image=thumb)
                self.app.load_image_async(image_url, (44, 62), set_thumb)

    def _select_all_with_link(self):
        visible_ids = {str(card.get("_doc_id") or "") for card in self.filtered_cards if card.get("linkMyp")}
        for doc_id, var in self.check_vars.items():
            if doc_id in visible_ids:
                var.set(True)
        self._update_summary()

    def _clear_selection(self):
        for var in self.check_vars.values():
            var.set(False)
        self._update_summary()

    def _selected_cards(self) -> list[dict]:
        selected = []
        for card in self.cards:
            doc_id = str(card.get("_doc_id") or "")
            var = self.check_vars.get(doc_id)
            if var is not None and var.get() and card.get("linkMyp"):
                selected.append(card)
        return selected

    def _current_unit_value(self, card: dict):
        for key in ("cheapestCertifiedPrice", "cheapestGeneralPrice", "averageGeneralPrice", "price", "Preço"):
            value = card.get(key)
            if value not in (None, ""):
                try:
                    return float(value)
                except Exception:
                    pass
        return None

    def _quoted_unit_value(self, result: dict):
        prices = result.get("prices") or {}
        value = prices.get("reference")
        try:
            return float(value) if value is not None else None
        except Exception:
            return None

    def _update_summary(self):
        selected = self._selected_cards()
        self.stat_selected.winfo_children()[0].configure(text=str(len(selected)))
        self.stat_quoted.winfo_children()[0].configure(text=str(len(self.results)))
        total = 0.0
        has_value = False
        for card in selected:
            doc_id = str(card.get("_doc_id") or "")
            result = self.results.get(doc_id)
            unit = self._quoted_unit_value(result) if result else self._current_unit_value(card)
            if unit is not None:
                total += unit * int(card.get("quantity") or 1)
                has_value = True
        self.stat_value.winfo_children()[0].configure(text=money(total) if has_value else "—")
        busy = self.quote_executor is not None or self.saving
        self.quote_btn.configure(state="disabled" if busy or not selected else "normal")
        self.save_btn.configure(state="normal" if self.results and not busy else "disabled")

    def _start_quote(self):
        selected = self._selected_cards()
        if not selected or self.quote_executor is not None:
            return
        self.results.clear()
        self.failed.clear()
        self.total_quote_jobs = len(selected)
        self.completed_quote_jobs = 0
        self.progress.set(0)
        self.progress_label.configure(text=f"Iniciando cotização de {len(selected)} cartas…", text_color=WARNING)
        self.quote_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="vault-myp-quote")
        self._update_summary()
        for card in selected:
            doc_id = str(card.get("_doc_id") or "")
            widget = self.row_widgets.get(doc_id)
            if widget:
                widget["status"].configure(text="consultando…", text_color=WARNING)
            future = self.quote_executor.submit(cotizar_carta, card.get("linkMyp"), card.get("condition") or "NM")
            future.add_done_callback(lambda fut, c=card: self.app.post_ui(lambda f=fut, card=c: self._quote_finished(card, f)))

    def _quote_finished(self, card: dict, future):
        if not self.active or not self.winfo_exists():
            return
        doc_id = str(card.get("_doc_id") or "")
        self.completed_quote_jobs += 1
        try:
            result = future.result()
        except Exception as exc:
            self.failed[doc_id] = str(exc)
            widget = self.row_widgets.get(doc_id)
            if widget:
                widget["status"].configure(text="falhou", text_color=DANGER)
        else:
            self.results[doc_id] = result
            self._apply_result_to_row(doc_id, result)
        self.progress.set(self.completed_quote_jobs / max(1, self.total_quote_jobs))
        self.progress_label.configure(text=f"{self.completed_quote_jobs}/{self.total_quote_jobs} concluídas · {len(self.results)} sucesso · {len(self.failed)} falhas", text_color=WARNING)
        if self.completed_quote_jobs >= self.total_quote_jobs:
            try:
                self.quote_executor.shutdown(wait=False, cancel_futures=False)
            except Exception:
                pass
            self.quote_executor = None
            self.progress_label.configure(text=f"Cotização concluída · {len(self.results)} cartas atualizadas na prévia" + (f" · {len(self.failed)} falharam" if self.failed else ""), text_color=SUCCESS if self.results else DANGER)
        self._update_summary()

    def _apply_result_to_row(self, doc_id: str, result: dict):
        widget = self.row_widgets.get(doc_id)
        if not widget:
            return
        value = self._quoted_unit_value(result)
        prices = result.get("prices") or {}
        condition_low = prices.get("conditionLowest")
        status_text = "MYP · mesmo estado" if condition_low is not None else "MYP · menor visível"
        widget["price"].configure(text=money(value), text_color=SUCCESS)
        widget["status"].configure(text=status_text, text_color=SUCCESS)

    def _save_results(self):
        if not self.results or self.saving:
            return
        self.saving = True
        self._update_summary()
        items = [(card, self.results.get(str(card.get("_doc_id") or ""))) for card in self.cards]
        items = [(card, result) for card, result in items if result]
        self.progress.set(0)
        self.progress_label.configure(text=f"Salvando {len(items)} cotações no Firestore…", text_color=WARNING)

        def worker():
            success = 0
            failures: list[tuple[str, str]] = []
            for index, (card, result) in enumerate(items, start=1):
                try:
                    save_quote(self.app.user, card, result)
                    success += 1
                except Exception as exc:
                    failures.append((str(card.get("_doc_id") or ""), str(exc)))
                self.app.post_ui(lambda i=index, total=len(items): self._save_progress(i, total))
            self.app.post_ui(lambda: self._save_done(success, failures))

        threading.Thread(target=worker, daemon=True, name="vault-firestore-save-quotes").start()

    def _save_progress(self, index: int, total: int):
        if not self.active or not self.winfo_exists():
            return
        self.progress.set(index / max(1, total))
        self.progress_label.configure(text=f"Salvando no Vault · {index}/{total}", text_color=WARNING)

    def _save_done(self, success: int, failures: list[tuple[str, str]]):
        self.saving = False
        if not self.active or not self.winfo_exists():
            return
        if failures:
            self.progress_label.configure(text=f"{success} cotações salvas · {len(failures)} falharam ao salvar", text_color=WARNING)
            for doc_id, _ in failures:
                widget = self.row_widgets.get(doc_id)
                if widget:
                    widget["status"].configure(text="erro ao salvar", text_color=DANGER)
        else:
            self.progress_label.configure(text=f"{success} cotações salvas no Vault com sucesso.", text_color=SUCCESS)
            self.app.toast(f"{success} cotações salvas no Vault.")
        self._update_summary()

    def _go_back(self):
        self.cleanup()
        self.app.show_home()

    def cleanup(self):
        if not self.active:
            return
        self.active = False
        if self.quote_executor is not None:
            try:
                self.quote_executor.shutdown(wait=False, cancel_futures=True)
            except Exception:
                pass
            self.quote_executor = None


# ---------------------------------------------------------------------------
# Revisão / fila local
# ---------------------------------------------------------------------------
class ReviewScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp", cards: list[dict], mode: str = "batch"):
        super().__init__(app)
        self.cards = cards
        self.mode = mode
        self.rows: dict[str, ctk.CTkFrame] = {}
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        if mode == "batch":
            title = "Revisar cartas resgatadas"
            subtitle = "Corrija idioma/estado, remova o que não quiser e salve a fila no app."
            back = app.show_home
        else:
            title = "Cartas esperando para registrar"
            subtitle = "Esta fila está salva localmente e pode ser revisada a qualquer momento."
            back = app.show_home
        Header(self, title, subtitle, back=back).grid(row=0, column=0, padx=32, pady=(26, 16), sticky="ew")

        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.grid(row=1, column=0, padx=32, sticky="nsew")
        self.scroll.grid_columnconfigure(0, weight=1)
        self._render_rows()

        bottom = ctk.CTkFrame(self, fg_color=BG)
        bottom.grid(row=2, column=0, padx=32, pady=22, sticky="ew")
        bottom.grid_columnconfigure(0, weight=1)
        self.summary = ctk.CTkLabel(bottom, text=self._summary_text(), text_color=MUTED)
        self.summary.grid(row=0, column=0, sticky="w")
        if mode == "batch":
            AppButton(bottom, text="Salvar no app", width=190, command=self._save_batch).grid(row=0, column=1, sticky="e")
        else:
            GhostButton(bottom, text="Registrar no site · em breve", width=210, state="disabled").grid(row=0, column=1, padx=(0, 10))
            AppButton(bottom, text="Salvar alterações", width=170, command=self._save_pending_edits).grid(row=0, column=2)

    def _summary_text(self):
        n = len(self.cards)
        return f"{n} carta" + ("s" if n != 1 else "")

    def _render_rows(self):
        for child in self.scroll.winfo_children():
            child.destroy()
        self.rows.clear()
        if not self.cards:
            ctk.CTkLabel(self.scroll, text="Nenhuma carta nesta fila.", text_color=MUTED).grid(row=0, column=0, pady=60)
            return
        for index, record in enumerate(self.cards):
            self._build_row(index, record)

    def _build_row(self, index: int, record: dict):
        row = ctk.CTkFrame(self.scroll, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=16)
        row.grid(row=index, column=0, pady=7, sticky="ew")
        row.grid_columnconfigure(1, weight=1)
        image_label = ctk.CTkLabel(row, text="…", width=78, height=106, text_color=MUTED)
        image_label.grid(row=0, column=0, rowspan=3, padx=14, pady=12)

        ctk.CTkLabel(row, text=record.get("name", "Carta"), font=ctk.CTkFont(size=17, weight="bold"), text_color=TEXT, anchor="w").grid(row=0, column=1, sticky="sw", pady=(14, 0))
        ctk.CTkLabel(row, text=f"{collector_text(record)} · {record.get('set_name', '')} · {record.get('rarity', '')}", text_color=MUTED, anchor="w").grid(row=1, column=1, sticky="nw", pady=(2, 4))

        controls = ctk.CTkFrame(row, fg_color="transparent")
        controls.grid(row=2, column=1, sticky="w", pady=(0, 13))
        ctk.CTkLabel(controls, text="Idioma", text_color=MUTED).pack(side="left", padx=(0, 6))
        language = ctk.StringVar(value=record.get("language") if record.get("language") in LANGUAGES else "BR")
        lang_menu = ctk.CTkOptionMenu(controls, values=LANGUAGES, variable=language, width=82, fg_color=PANEL_2, button_color=ACCENT, command=lambda v, r=record: r.__setitem__("language", v))
        lang_menu.pack(side="left", padx=(0, 15))
        ctk.CTkLabel(controls, text="Estado", text_color=MUTED).pack(side="left", padx=(0, 6))
        condition = ctk.StringVar(value=record.get("condition") if record.get("condition") in CONDITIONS else "NM")
        cond_menu = ctk.CTkOptionMenu(controls, values=CONDITIONS, variable=condition, width=82, fg_color=PANEL_2, button_color=ACCENT, command=lambda v, r=record: r.__setitem__("condition", v))
        cond_menu.pack(side="left")

        buttons = ctk.CTkFrame(row, fg_color="transparent")
        buttons.grid(row=0, column=2, rowspan=3, padx=14, pady=12)
        GhostButton(buttons, text="Detalhes", width=90, command=lambda r=record: CardDetails(self.app, r)).pack(pady=4)
        GhostButton(buttons, text="MYP", width=90, command=lambda r=record: webbrowser.open(r.get("myp_link", ""))).pack(pady=4)
        GhostButton(buttons, text="Remover", width=90, text_color=DANGER, command=lambda r=record: self._remove(r)).pack(pady=4)

        def set_thumb(image):
            if not row.winfo_exists():
                return
            if image is None:
                image_label.configure(text="?")
                return
            thumb = ctk.CTkImage(light_image=image, dark_image=image, size=(70, 98))
            image_label._vault_image = thumb
            image_label.configure(image=thumb, text="")

        self.app.load_image_async(record.get("image_url"), (70, 98), set_thumb)

    def _remove(self, record: dict):
        try:
            self.cards.remove(record)
        except ValueError:
            return
        self._render_rows()
        self.summary.configure(text=self._summary_text())

    def _save_batch(self):
        if not self.cards:
            self.app.show_home()
            return
        # Cada captura tem local_id próprio. Se a mesma fila for salva novamente,
        # evita duplicação acidental pelo identificador local.
        existing_ids = {c.get("local_id") for c in self.app.pending_cards}
        self.app.pending_cards.extend(c for c in self.cards if c.get("local_id") not in existing_ids)
        save_pending(self.app.user.uid, self.app.pending_cards)
        self.app.toast(f"{len(self.cards)} carta(s) salvas na fila local.")
        self.app.show_home()

    def _save_pending_edits(self):
        self.app.pending_cards = self.cards
        save_pending(self.app.user.uid, self.app.pending_cards)
        self.app.toast("Alterações salvas.")
        self.app.show_home()


# ---------------------------------------------------------------------------
# Aplicação
# ---------------------------------------------------------------------------
class VaultScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Vault TCG Scanner")
        self.geometry("1320x840")
        self.minsize(1080, 700)
        self.configure(fg_color=BG)
        self.user: Optional[VaultUser] = None
        self.pending_cards: list[dict] = []
        self.current_screen: Optional[BaseScreen] = None
        self.ocr_reader: Optional[easyocr.Reader] = None
        self.ocr_lock = threading.Lock()
        self.image_executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="vault-images")
        self.image_cache: dict[str, Image.Image] = {}
        self._toast_window: Optional[ctk.CTkToplevel] = None
        self.ui_queue: queue.Queue[Callable] = queue.Queue()
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(25, self._drain_ui_queue)
        self.show_login()


    def post_ui(self, callback: Callable):
        """Agenda uma função da thread principal sem tocar no Tk a partir de workers."""
        self.ui_queue.put(callback)

    def _drain_ui_queue(self):
        try:
            while True:
                callback = self.ui_queue.get_nowait()
                try:
                    callback()
                except Exception:
                    pass
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(25, self._drain_ui_queue)

    def set_screen(self, screen: BaseScreen):
        if self.current_screen is not None:
            try:
                self.current_screen.cleanup()
            except Exception:
                pass
            try:
                self.current_screen.destroy()
            except Exception:
                pass
        self.current_screen = screen
        screen.pack(fill="both", expand=True)

    def show_login(self):
        self.set_screen(LoginScreen(self))

    def show_home(self):
        self.set_screen(HomeScreen(self))

    def show_register_methods(self):
        self.set_screen(RegisterMethodsScreen(self))

    def show_camera(self):
        self.set_screen(CameraScreen(self))

    def show_photo(self):
        self.set_screen(PhotoScreen(self))

    def show_quote(self):
        self.set_screen(QuoteScreen(self))

    def show_review(self, cards: list[dict]):
        self.set_screen(ReviewScreen(self, cards, mode="batch"))

    def show_pending(self):
        # O editor trabalha diretamente sobre uma cópia; só persiste ao salvar.
        cards = [dict(card) for card in self.pending_cards]
        self.set_screen(ReviewScreen(self, cards, mode="pending"))

    def logout(self):
        self.user = None
        self.pending_cards = []
        self.show_login()

    def load_image_async(self, url: str, size: tuple[int, int], callback: Callable[[Optional[Image.Image]], None]):
        url = str(url or "").strip()
        if not url:
            self.post_ui(lambda: callback(None))
            return
        key = hashlib.sha1(url.encode("utf-8", "ignore")).hexdigest()
        if key in self.image_cache:
            image = self.image_cache[key].copy()
            image.thumbnail(size, Image.Resampling.LANCZOS)
            self.post_ui(lambda: callback(image))
            return

        def worker():
            try:
                response = requests.get(url, timeout=12, headers={"User-Agent": "VaultTCGScanner/1.0"})
                response.raise_for_status()
                image = Image.open(io.BytesIO(response.content)).convert("RGB")
                self.image_cache[key] = image.copy()
                image.thumbnail(size, Image.Resampling.LANCZOS)
            except Exception:
                image = None
            self.post_ui(lambda: callback(image))

        self.image_executor.submit(worker)

    def toast(self, message: str):
        if self._toast_window and self._toast_window.winfo_exists():
            self._toast_window.destroy()
        win = ctk.CTkToplevel(self)
        self._toast_window = win
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        label = ctk.CTkLabel(win, text=message, fg_color="#172236", text_color=TEXT, corner_radius=12)
        label.pack(ipadx=18, ipady=10)
        self.update_idletasks()
        x = self.winfo_rootx() + self.winfo_width() - 350
        y = self.winfo_rooty() + 30
        win.geometry(f"+{x}+{y}")
        self.after(2400, lambda: win.destroy() if win.winfo_exists() else None)

    def _close(self):
        if self.current_screen:
            try:
                self.current_screen.cleanup()
            except Exception:
                pass
        try:
            self.image_executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.destroy()


def main():
    app = VaultScannerApp()
    app.mainloop()


if __name__ == "__main__":
    main()
