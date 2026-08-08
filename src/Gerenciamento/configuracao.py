from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

PASTA_GERENCIAMENTO = Path(__file__).resolve().parent
RAIZ_PROJETO = PASTA_GERENCIAMENTO.parent
PASTA_COLECOES = RAIZ_PROJETO / "colecoes"
PASTA_NAO_FORMATADAS = RAIZ_PROJETO / "colecoes-nao-formatadas"
PASTA_IMAGENS = RAIZ_PROJETO.parent / "public" / "imagens"
PASTA_RELATORIOS_NOME = "relatorios"
PASTA_HISTORICO_NOME = "historico"
ARQUIVO_PERFIL = "perfil.json"
ARQUIVO_ATUALIZACAO = "atualizacao.json"
ARQUIVO_CONFIG = PASTA_GERENCIAMENTO / "config.json"

ARQUIVOS_INVENTARIO = {
    "cartas": "inventario-cartas.json",
    "boosters": "inventario-boosters.json",
    "kits": "inventario-kits.json",
    "albuns": "inventario-albuns.json",
}
ARQUIVOS_HISTORICO = {
    "cartas": "cartas.jsonl",
    "boosters": "boosters.jsonl",
}
ARQUIVOS_LEGADOS = {
    "cartas": "inventario-cartas.csv",
    "boosters": "inventario-boosters.csv",
    "kits": "inventario-kits.csv",
    "albuns": "inventario-albuns.csv",
}

PADRAO_CONFIG: dict[str, Any] = {
    "esperaPagina": 5,
    "intervaloTentativa": 1.5,
    "tentativas": 3,
    "maxTentativasPagina": 120,
    "vendaRapida": 0.95,
    "minimoCerteiro": 0.60,
    "usarOCR": True,
    "salvarParcialACadaItem": True,
    "fatoresEstado": {
        "M": 1.0,
        "NM": 1.0,
        "SP": 0.90,
        "MP": 0.75,
        "HP": 0.50,
        "D": 0.30,
    },
}


def _carregar_config() -> dict[str, Any]:
    dados = dict(PADRAO_CONFIG)
    dados["fatoresEstado"] = dict(PADRAO_CONFIG["fatoresEstado"])
    if ARQUIVO_CONFIG.is_file():
        try:
            externo = json.loads(ARQUIVO_CONFIG.read_text(encoding="utf-8-sig"))
            if isinstance(externo, dict):
                dados.update({k: v for k, v in externo.items() if k != "fatoresEstado"})
                if isinstance(externo.get("fatoresEstado"), dict):
                    dados["fatoresEstado"].update(externo["fatoresEstado"])
        except (OSError, json.JSONDecodeError):
            pass
    return dados


CONFIG = _carregar_config()
INTERVALO_TENTATIVA = float(CONFIG.get("intervaloTentativa", 1.5))
MAX_TENTATIVAS_PAGINA = int(CONFIG.get("maxTentativasPagina", 120))
ESPERA_PAGINA = float(CONFIG.get("esperaPagina", 5))
TENTATIVAS = max(1, int(CONFIG.get("tentativas", 3)))
VENDA_RAPIDA = float(CONFIG.get("vendaRapida", 0.95))
MINIMO_CERTEIRO = float(CONFIG.get("minimoCerteiro", 0.60))
USAR_OCR = bool(CONFIG.get("usarOCR", True))
SALVAR_PARCIAL = bool(CONFIG.get("salvarParcialACadaItem", True))
ESTADOS_ORDEM = ("M", "NM", "SP", "MP", "HP", "D")
FATORES_ESTADO = {estado: float(CONFIG["fatoresEstado"].get(estado, 1.0)) for estado in ESTADOS_ORDEM}


def chave_texto(valor: object) -> str:
    texto = "" if valor is None else str(valor)
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def pasta_nao_formatadas() -> Path:
    PASTA_NAO_FORMATADAS.mkdir(parents=True, exist_ok=True)
    return PASTA_NAO_FORMATADAS


def pasta_colecoes() -> Path:
    PASTA_COLECOES.mkdir(parents=True, exist_ok=True)
    return PASTA_COLECOES
