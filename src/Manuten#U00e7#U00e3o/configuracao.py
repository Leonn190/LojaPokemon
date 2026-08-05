from __future__ import annotations

import re
import unicodedata
from pathlib import Path

PASTA_MANUTENCAO = Path(__file__).resolve().parent
RAIZ_PROJETO = PASTA_MANUTENCAO.parent


def _decodificar_nome_zip(nome: str) -> str:
    """Converte nomes como cole#U00e7#U00f5es, gerados por alguns ZIPs."""

    def substituir(correspondencia: re.Match[str]) -> str:
        try:
            return chr(int(correspondencia.group(1), 16))
        except ValueError:
            return correspondencia.group(0)

    return re.sub(r"#U([0-9a-fA-F]{4})", substituir, nome)


def chave_texto(valor: object) -> str:
    texto = _decodificar_nome_zip("" if valor is None else str(valor))
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^A-Z0-9]", "", texto.upper())


def localizar_pasta(*nomes: str, criar_como: str) -> Path:
    """Localiza a pasta mesmo se o ZIP tiver escapado os acentos."""

    chaves = {chave_texto(nome) for nome in nomes}
    if RAIZ_PROJETO.is_dir():
        for item in RAIZ_PROJETO.iterdir():
            if item.is_dir() and chave_texto(item.name) in chaves:
                return item
    destino = RAIZ_PROJETO / criar_como
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def pasta_nao_formatadas() -> Path:
    return localizar_pasta(
        "Coleções não formatadas",
        "Colecoes nao formatadas",
        criar_como="Coleções não formatadas",
    )


def pasta_colecoes() -> Path:
    return localizar_pasta(
        "coleções",
        "colecoes",
        criar_como="coleções",
    )


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
    "ID",
    "Nome",
    "Descrição",
    "Formato",
    "Páginas JSON",
    "Progresso",
    "Quantidade",
    "Imagem",
    "À venda",
]
