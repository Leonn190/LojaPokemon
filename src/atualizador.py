"""Atualiza preços da Liga usando um único Chrome e abas temporárias.

Uso:
    python atualizador.py
    python atualizador.py --colecao Leon19
"""

from __future__ import annotations

import argparse
import csv
from decimal import Decimal
from pathlib import Path

from formatador import (
    PASTA_COLECOES_FORMATADAS,
    SessaoLiga,
    formatar_decimal_csv,
)


def ler_csv(caminho: Path) -> tuple[list[str], list[dict[str, str]]]:
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        return list(leitor.fieldnames or []), list(leitor)


def escrever_csv(caminho: Path, cabecalhos: list[str], linhas: list[dict[str, str]]) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(
            arquivo,
            fieldnames=cabecalhos,
            extrasaction="ignore",
            lineterminator="\n",
        )
        escritor.writeheader()
        escritor.writerows(linhas)


def atualizar_cartas(caminho: Path, sessao: SessaoLiga) -> None:
    if not caminho.is_file():
        return
    cabecalhos, linhas = ler_csv(caminho)
    if "Menor Liga" not in cabecalhos:
        cabecalhos.append("Menor Liga")

    for indice, linha in enumerate(linhas, start=1):
        link = (linha.get("Link Liga") or "").strip()
        if not link:
            print(f"  Carta {indice}: ignorada (sem Link Liga)")
            continue
        try:
            dados = sessao.consultar_carta(
                link,
                (linha.get("Idioma") or "BR").strip(),
                (linha.get("Estado") or "NM").strip(),
            )
            preco = dados.get("preco")
            if isinstance(preco, Decimal):
                linha["Menor Liga"] = formatar_decimal_csv(preco)
                print(f"  Carta {indice}: {linha['Menor Liga']}")
            else:
                print(f"  Carta {indice}: preço não encontrado")
        except Exception as erro:
            print(f"  Carta {indice}: não atualizada ({erro})")

    escrever_csv(caminho, cabecalhos, linhas)


def atualizar_boosters(caminho: Path, sessao: SessaoLiga) -> None:
    if not caminho.is_file():
        return
    cabecalhos, linhas = ler_csv(caminho)
    coluna_preco = "Preço Liga mais barato"
    if coluna_preco not in cabecalhos:
        cabecalhos.append(coluna_preco)

    for indice, linha in enumerate(linhas, start=1):
        link = (linha.get("Link Liga") or "").strip()
        if not link:
            print(f"  Booster {indice}: ignorado (a coleção não possui Link Liga para ele)")
            continue
        try:
            dados = sessao.consultar_booster(link)
            preco = dados.get("preco")
            if isinstance(preco, Decimal):
                linha[coluna_preco] = formatar_decimal_csv(preco)
                print(f"  Booster {indice}: {linha[coluna_preco]}")
            else:
                print(f"  Booster {indice}: preço não encontrado")
        except Exception as erro:
            print(f"  Booster {indice}: não atualizado ({erro})")

    escrever_csv(caminho, cabecalhos, linhas)


def escolher_colecao(nome: str | None) -> Path:
    PASTA_COLECOES_FORMATADAS.mkdir(parents=True, exist_ok=True)
    colecoes = sorted(path for path in PASTA_COLECOES_FORMATADAS.iterdir() if path.is_dir())
    if nome:
        selecionada = PASTA_COLECOES_FORMATADAS / nome
        if selecionada in colecoes:
            return selecionada
        raise FileNotFoundError(f"Coleção não encontrada: {nome}")
    if not colecoes:
        raise FileNotFoundError("Nenhuma coleção formatada foi encontrada.")
    print("Coleções disponíveis:")
    for indice, colecao in enumerate(colecoes, start=1):
        print(f"  {indice}. {colecao.name}")
    while True:
        try:
            return colecoes[int(input("Escolha o número da coleção: ")) - 1]
        except (ValueError, IndexError):
            print("Escolha um número da lista.")


def main() -> None:
    argumentos = argparse.ArgumentParser(
        description="Atualiza os preços da Liga Pokémon sem reabrir o Chrome a cada item.",
    )
    argumentos.add_argument("--colecao", help="Nome da pasta da coleção, por exemplo Leon19.")
    argumentos.add_argument(
        "--lote",
        type=int,
        default=1,
        help="Mantido por compatibilidade; agora todas as consultas usam um único Chrome.",
    )
    opcoes = argumentos.parse_args()
    colecao = escolher_colecao(opcoes.colecao)
    with SessaoLiga() as sessao:
        atualizar_cartas(colecao / "inventario-cartas.csv", sessao)
        atualizar_boosters(colecao / "inventario-boosters.csv", sessao)
    print(f"Preços atualizados em: {colecao}")


if __name__ == "__main__":
    main()
