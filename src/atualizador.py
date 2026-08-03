"""Atualiza em massa os menores preços da Liga de uma coleção já publicada.

Uso: python atualizador.py
     python atualizador.py --colecao Leon19 --lote 10
"""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import shutil
import tempfile
from pathlib import Path
from typing import Any

from regulador import (
    PASTA_COLECOES_FORMATADAS,
    PASTA_PERFIL_CHROME,
    consultar,
    consultar_booster,
    formatar_reais,
)


def ler_csv(caminho: Path) -> tuple[list[str], list[dict[str, str]]]:
    with caminho.open("r", encoding="utf-8-sig", newline="") as arquivo:
        leitor = csv.DictReader(arquivo)
        return list(leitor.fieldnames or []), list(leitor)


def escrever_csv(caminho: Path, cabecalhos: list[str], linhas: list[dict[str, str]]) -> None:
    with caminho.open("w", encoding="utf-8", newline="") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=cabecalhos)
        escritor.writeheader()
        escritor.writerows(linhas)


def clonar_perfil(destino: Path) -> Path:
    """Copia os cookies obtidos na primeira aba para um trabalhador do lote."""

    if PASTA_PERFIL_CHROME.exists():
        shutil.copytree(
            PASTA_PERFIL_CHROME,
            destino,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("Singleton*", "LOCK", "lockfile"),
        )
    return destino


def atualizar_carta(indice: int, linha: dict[str, str], pasta_perfil: Path) -> tuple[int, str, str]:
    link = (linha.get("Link Liga") or "").strip()
    if not link:
        return indice, "", "sem Link Liga"
    try:
        dados = consultar(
            link,
            (linha.get("Idioma") or "BR").strip(),
            (linha.get("Estado") or "NM").strip(),
            pasta_perfil,
        )
        preco = dados.get("preco")
        return indice, formatar_reais(preco) if preco is not None else "", "ok"
    except Exception as erro:
        return indice, "", str(erro)


def atualizar_booster(indice: int, linha: dict[str, str], pasta_perfil: Path) -> tuple[int, str, str]:
    link = (linha.get("Link Liga") or "").strip()
    if not link:
        return indice, "", "sem Link Liga"
    try:
        dados = consultar_booster(link, pasta_perfil)
        preco = dados.get("preco")
        return indice, formatar_reais(preco) if preco is not None else "", "ok"
    except Exception as erro:
        return indice, "", str(erro)


def atualizar_arquivo(caminho: Path, tipo: str, lote: int) -> None:
    if not caminho.is_file():
        return
    cabecalhos, linhas = ler_csv(caminho)
    if not linhas:
        return
    coluna_preco = "Preço Mais Baixo Liga"
    if coluna_preco not in cabecalhos:
        cabecalhos.append(coluna_preco)
    trabalhador = atualizar_carta if tipo == "carta" else atualizar_booster
    print(f"Abrindo a primeira aba para {tipo}; confirme a verificação da Liga, se necessário...")
    primeiro_indice, primeiro_preco, primeiro_status = trabalhador(0, linhas[0], PASTA_PERFIL_CHROME)
    if primeiro_preco:
        linhas[primeiro_indice][coluna_preco] = primeiro_preco
        print(f"  {tipo} 1: {primeiro_preco}")
    else:
        print(f"  {tipo} 1: não atualizado ({primeiro_status})")
    if len(linhas) == 1:
        escrever_csv(caminho, cabecalhos, linhas)
        return
    print(f"Atualizando os demais {len(linhas) - 1} {tipo}(s) em lotes de até {lote}...")
    with tempfile.TemporaryDirectory(prefix="loja-pokemon-atualizador-") as temporario:
        raiz_perfis = Path(temporario)
        with concurrent.futures.ThreadPoolExecutor(max_workers=lote) as executor:
            futuros = []
            for indice, linha in enumerate(linhas[1:], start=1):
                perfil = clonar_perfil(raiz_perfis / f"perfil-{indice % lote}")
                futuros.append(executor.submit(trabalhador, indice, linha, perfil))
            for futuro in concurrent.futures.as_completed(futuros):
                indice, preco, status = futuro.result()
                if preco:
                    linhas[indice][coluna_preco] = preco
                    print(f"  {tipo} {indice + 1}: {preco}")
                else:
                    print(f"  {tipo} {indice + 1}: não atualizado ({status})")
    escrever_csv(caminho, cabecalhos, linhas)


def escolher_colecao(nome: str | None) -> Path:
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
    argumentos = argparse.ArgumentParser(description="Atualiza os preços da Liga Pokémon em uma coleção.")
    argumentos.add_argument("--colecao", help="Nome da pasta da coleção, por exemplo Leon19.")
    argumentos.add_argument("--lote", type=int, default=10, help="Quantidade máxima de abas simultâneas (padrão: 10).")
    opcoes = argumentos.parse_args()
    lote = max(1, min(opcoes.lote, 10))
    colecao = escolher_colecao(opcoes.colecao)
    print("A primeira consulta abrirá o Chrome com seu perfil da Liga Pokémon.")
    print("Se a Liga pedir verificação, conclua-a nessa primeira aba; os lotes seguintes reutilizam os cookies.")
    atualizar_arquivo(colecao / "inventario-cartas.csv", "carta", lote)
    atualizar_arquivo(colecao / "inventario-boosters.csv", "booster", lote)
    print(f"Preços atualizados em: {colecao}")


if __name__ == "__main__":
    main()
