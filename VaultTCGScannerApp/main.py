#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import io
import queue
import threading
import time
import uuid
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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


# ---------------------------------------------------------------------------
# Tema
# ---------------------------------------------------------------------------
BG = "#080B12"
PANEL = "#0E1420"
PANEL_2 = "#111A29"
BORDER = "#263247"
TEXT = "#F7F9FC"
MUTED = "#8F9DB2"
ACCENT = "#7A5CFF"
ACCENT_HOVER = "#6548E8"
SUCCESS = "#41D39A"
WARNING = "#F4C15D"
DANGER = "#EF6574"
CAMERA_BG = "#03050A"

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


def detect_card_regions(frame: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
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
        if len(selected) >= MAX_ROIS_PER_CYCLE:
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
        kwargs.setdefault("height", 42)
        kwargs.setdefault("corner_radius", 12)
        kwargs.setdefault("font", ctk.CTkFont(size=14, weight="bold"))
        kwargs.setdefault("fg_color", ACCENT)
        kwargs.setdefault("hover_color", ACCENT_HOVER)
        super().__init__(master, **kwargs)


class GhostButton(ctk.CTkButton):
    def __init__(self, master, **kwargs):
        kwargs.setdefault("height", 38)
        kwargs.setdefault("corner_radius", 10)
        kwargs.setdefault("font", ctk.CTkFont(size=13, weight="bold"))
        kwargs.setdefault("fg_color", "transparent")
        kwargs.setdefault("hover_color", PANEL_2)
        kwargs.setdefault("border_width", 1)
        kwargs.setdefault("border_color", BORDER)
        kwargs.setdefault("text_color", TEXT)
        super().__init__(master, **kwargs)


class Header(ctk.CTkFrame):
    def __init__(self, master, title: str, subtitle: str = "", back: Optional[Callable] = None):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        if back:
            GhostButton(self, text="←", width=44, command=back).grid(row=0, column=0, rowspan=2, padx=(0, 14), sticky="w")
        ctk.CTkLabel(self, text=title, font=ctk.CTkFont(size=26, weight="bold"), text_color=TEXT).grid(
            row=0, column=1, sticky="w"
        )
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=ctk.CTkFont(size=13), text_color=MUTED).grid(
                row=1, column=1, sticky="w", pady=(2, 0)
            )


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
        wrapper.grid(row=0, column=0)

        ctk.CTkLabel(wrapper, text="VAULT", font=ctk.CTkFont(size=17, weight="bold"), text_color=ACCENT).pack()
        ctk.CTkLabel(wrapper, text="TCG Scanner", font=ctk.CTkFont(size=38, weight="bold"), text_color=TEXT).pack(pady=(0, 8))
        ctk.CTkLabel(wrapper, text="Entre com a mesma conta usada no site.", font=ctk.CTkFont(size=14), text_color=MUTED).pack(pady=(0, 24))

        card = ctk.CTkFrame(wrapper, width=430, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=20)
        card.pack()
        card.pack_propagate(False)
        card.configure(height=330)

        ctk.CTkLabel(card, text="Entrar na conta", font=ctk.CTkFont(size=20, weight="bold"), text_color=TEXT).pack(anchor="w", padx=28, pady=(26, 14))
        self.email = ctk.CTkEntry(card, placeholder_text="E-mail", height=45, corner_radius=11, fg_color=PANEL_2, border_color=BORDER)
        self.email.pack(fill="x", padx=28, pady=7)
        self.password = ctk.CTkEntry(card, placeholder_text="Senha", show="•", height=45, corner_radius=11, fg_color=PANEL_2, border_color=BORDER)
        self.password.pack(fill="x", padx=28, pady=7)
        self.feedback = ctk.CTkLabel(card, text="", font=ctk.CTkFont(size=12), text_color=DANGER, wraplength=360)
        self.feedback.pack(fill="x", padx=28, pady=(2, 2))
        self.login_btn = AppButton(card, text="Entrar", command=self._login)
        self.login_btn.pack(fill="x", padx=28, pady=(7, 24))
        self.password.bind("<Return>", lambda _: self._login())

    def _login(self):
        email = self.email.get().strip()
        password = self.password.get()
        self.feedback.configure(text="Conectando…", text_color=MUTED)
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
        self.login_btn.configure(state="normal", text="Entrar")

    def _login_ok(self, user: VaultUser):
        self.app.user = user
        self.app.pending_cards = load_pending(user.uid)
        self.password.delete(0, "end")
        self.app.show_home()


# ---------------------------------------------------------------------------
# Home e seleção de método
# ---------------------------------------------------------------------------
class HomeScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self, fg_color="transparent")
        top.grid(row=0, column=0, padx=42, pady=(30, 8), sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(top, text="Vault TCG", font=ctk.CTkFont(size=24, weight="bold"), text_color=TEXT).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(top, text=app.user.email if app.user else "", text_color=MUTED).grid(row=1, column=0, sticky="w")
        GhostButton(top, text="Sair", width=86, command=app.logout).grid(row=0, column=1, rowspan=2, sticky="e")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=1, column=0, padx=42, pady=(18, 38), sticky="nsew")
        body.grid_columnconfigure((0, 1), weight=1, uniform="cards")
        body.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(body, text="O que você quer fazer?", font=ctk.CTkFont(size=31, weight="bold"), text_color=TEXT).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 18))

        register = self._action_card(body, "Registrar novas cartas", "Use câmera ou foto para localizar a carta e encontrar seu link da MYP.", "Abrir registro", app.show_register_methods)
        register.grid(row=1, column=0, padx=(0, 10), sticky="nsew")

        quote = self._action_card(body, "Nova cotização", "A cotização ficará disponível em uma próxima etapa do app.", "Em breve", lambda: None, disabled=True)
        quote.grid(row=1, column=1, padx=(10, 0), sticky="nsew")

        pending = ctk.CTkFrame(body, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=18)
        pending.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(20, 0))
        pending.grid_columnconfigure(1, weight=1)
        count = len(app.pending_cards)
        badge = ctk.CTkLabel(pending, text=str(count), width=48, height=48, corner_radius=14, fg_color=PANEL_2, text_color=ACCENT, font=ctk.CTkFont(size=20, weight="bold"))
        badge.grid(row=0, column=0, rowspan=2, padx=18, pady=16)
        ctk.CTkLabel(pending, text="Cartas esperando para registrar", font=ctk.CTkFont(size=16, weight="bold"), text_color=TEXT).grid(row=0, column=1, sticky="sw")
        ctk.CTkLabel(pending, text="Ficam salvas localmente neste computador até a integração final com o site.", text_color=MUTED).grid(row=1, column=1, sticky="nw", pady=(2, 0))
        GhostButton(pending, text="Ver cartas", width=110, command=app.show_pending, state="normal" if count else "disabled").grid(row=0, column=2, rowspan=2, padx=18)

    def _action_card(self, master, title, desc, button_text, command, disabled=False):
        frame = ctk.CTkFrame(master, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=20)
        ctk.CTkLabel(frame, text=title, font=ctk.CTkFont(size=22, weight="bold"), text_color=TEXT).pack(anchor="w", padx=24, pady=(26, 8))
        ctk.CTkLabel(frame, text=desc, font=ctk.CTkFont(size=14), text_color=MUTED, wraplength=420, justify="left").pack(anchor="w", padx=24)
        btn = AppButton(frame, text=button_text, command=command, state="disabled" if disabled else "normal")
        btn.pack(fill="x", side="bottom", padx=24, pady=24)
        return frame


class RegisterMethodsScreen(BaseScreen):
    def __init__(self, app: "VaultScannerApp"):
        super().__init__(app)
        self.grid_columnconfigure(0, weight=1)
        Header(self, "Registrar novas cartas", "Escolha como as cartas serão identificadas.", back=app.show_home).grid(row=0, column=0, padx=42, pady=(32, 20), sticky="ew")

        methods = ctk.CTkFrame(self, fg_color="transparent")
        methods.grid(row=1, column=0, padx=42, sticky="nsew")
        methods.grid_columnconfigure((0, 1), weight=1, uniform="m")

        cam = ctk.CTkFrame(methods, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=20)
        cam.grid(row=0, column=0, padx=(0, 10), sticky="nsew")
        ctk.CTkLabel(cam, text="Câmera", font=ctk.CTkFont(size=23, weight="bold"), text_color=TEXT).pack(anchor="w", padx=24, pady=(25, 7))
        ctk.CTkLabel(cam, text="Detecção automática e contínua. Mostre a carta; o app identifica, consulta a MYP e adiciona na sessão.", wraplength=430, justify="left", text_color=MUTED).pack(anchor="w", padx=24)
        AppButton(cam, text="Abrir câmera", command=app.show_camera).pack(fill="x", padx=24, pady=24, side="bottom")

        photo = ctk.CTkFrame(methods, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=20)
        photo.grid(row=0, column=1, padx=(10, 0), sticky="nsew")
        ctk.CTkLabel(photo, text="Foto", font=ctk.CTkFont(size=23, weight="bold"), text_color=TEXT).pack(anchor="w", padx=24, pady=(25, 7))
        ctk.CTkLabel(photo, text="Importação de imagens do computador será adicionada depois.", wraplength=430, justify="left", text_color=MUTED).pack(anchor="w", padx=24)
        AppButton(photo, text="Em breve", state="disabled").pack(fill="x", padx=24, pady=24, side="bottom")


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
            cv2.polylines(shown, [poly.astype(np.int32)], True, (122, 92, 255), 3, cv2.LINE_AA)
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
        self.geometry("1240x790")
        self.minsize(1050, 680)
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
