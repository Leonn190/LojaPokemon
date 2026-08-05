from __future__ import annotations

import re
import unicodedata
from pathlib import Path

PASTA_GERENCIAMENTO = Path(__file__).resolve().parent
RAIZ_PROJETO = PASTA_GERENCIAMENTO.parent
PASTA_COLECOES = RAIZ_PROJETO / "colecoes"
PASTA_NAO_FORMATADAS = RAIZ_PROJETO / "colecoes-nao-formatadas"


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


PASTA_IMAGENS = RAIZ_PROJETO.parent / "public" / "imagens"
ARQUIVO_PERFIL = "perfil.json"
ARQUIVO_ATUALIZACAO = "atualizacao.json"

INTERVALO_TENTATIVA = 1.5
MAX_TENTATIVAS_PAGINA = 120

ESTADOS_ORDEM = ("M", "NM", "SP", "MP", "HP", "D")
PERCENTUAL_POR_NIVEL = 20

COLUNAS_CARTAS = [
    "Nome",
    "Número",
    "Coleção",
    "Idioma",
    "Estado",
    "Ano",
    "Tipo",
    "Link Liga",
    "Link MYP",
    "Link Cardmarket",
    "Link Tcgplayer",
    "Link PriceCharting",
    "Minimo",
    "Venda Rapida",
    "Menor Liga",
    "Preço Médio Liga",
    "Preço",
    "Alteração de preço",
    "Quantidade",
    "À venda",
]

COLUNAS_BOOSTERS = [
    "Tipo de pacote",
    "Quantidade",
    "Preço mínimo",
    "Venda rápida",
    "Preço Liga mais barato",
    "Preço médio Liga",
    "Preço",
    "Alteração de preço",
    "Link Liga",
    "À venda",
]

COLUNAS_KITS = [
    "Nome",
    "Descrição",
    "Preço",
    "Quantidade",
    "Conteúdo",
    "Conteúdo JSON",
    "Valor avulso",
    "Desconto",
    "Imagem",
    "À venda",
]

COLUNAS_ALBUNS = [
    "Nome",
    "Descrição",
    "Progresso",
    "Quantidade",
    "Imagem",
    "À venda",
]
