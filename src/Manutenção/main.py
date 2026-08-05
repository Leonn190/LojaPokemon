from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def garantir_dependencias() -> None:
    """Instala automaticamente somente o que estiver faltando."""

    dependencias = {
        "selenium": "selenium>=4.18",
        "PIL": "Pillow>=10.0",
        "ddddocr": "ddddocr>=1.5.6",
    }
    faltando = [pacote for modulo, pacote in dependencias.items() if importlib.util.find_spec(modulo) is None]
    if not faltando:
        return
    print("Dependências ausentes. Instalando automaticamente:")
    for pacote in faltando:
        print(f"  - {pacote}")
    subprocess.check_call([sys.executable, "-m", "pip", "install", *faltando])


def escolher(titulo: str, itens: list[T], rotulo) -> T:
    if not itens:
        raise FileNotFoundError(f"Nenhum item disponível para: {titulo}")
    if len(itens) == 1:
        print(f"{titulo}: {rotulo(itens[0])}")
        return itens[0]
    print(f"\n{titulo}")
    for indice, item in enumerate(itens, start=1):
        print(f"  {indice}. {rotulo(item)}")
    while True:
        resposta = input("Escolha o número: ").strip()
        try:
            return itens[int(resposta) - 1]
        except (ValueError, IndexError):
            print("Digite um número válido da lista.")


def escolher_modo_preco() -> str:
    print("\nQual valor deve preencher a coluna Preço?")
    print("  1. Menor preço encontrado na Liga")
    print("  2. Média das ofertas compatíveis da Liga")
    while True:
        resposta = input("Escolha 1 ou 2: ").strip()
        if resposta == "1":
            return "menor"
        if resposta == "2":
            return "media"
        print("Escolha somente 1 ou 2.")


def executar_formatacao() -> None:
    from configuracao import ARQUIVO_PERFIL
    from manutencao import formatar_nova_colecao, listar_pacotes

    pacotes = listar_pacotes(ARQUIVO_PERFIL)
    pacote = escolher(
        "Coleções não formatadas disponíveis",
        pacotes,
        lambda item: item.name,
    )
    modo = escolher_modo_preco()
    destino = formatar_nova_colecao(pacote, modo)
    print(f"\nColeção formatada com sucesso em:\n{destino}")


def executar_atualizacao() -> None:
    from configuracao import ARQUIVO_ATUALIZACAO
    from manutencao import atualizar_colecao, listar_pacotes

    pacotes = listar_pacotes(ARQUIVO_ATUALIZACAO)
    pacote = escolher(
        "Atualizações disponíveis",
        pacotes,
        lambda item: item.name,
    )
    destino = atualizar_colecao(pacote)
    print(f"\nAtualização aplicada com sucesso em:\n{destino}")


def executar_cotizacao() -> None:
    from manutencao import cotizar_colecao, listar_colecoes

    colecao = escolher(
        "Coleções disponíveis para cotização",
        listar_colecoes(),
        lambda item: item.name,
    )
    destino = cotizar_colecao(colecao)
    print(f"\nCotização concluída com sucesso em:\n{destino}")


def main() -> None:
    garantir_dependencias()
    acoes = {
        "1": executar_formatacao,
        "2": executar_atualizacao,
        "3": executar_cotizacao,
    }
    while True:
        print("\n" + "=" * 58)
        print("NEXUS TCG — MANUTENÇÃO DE COLEÇÕES")
        print("=" * 58)
        print("  1. Formatar nova coleção")
        print("  2. Atualizar coleção com novidades")
        print("  3. Fazer a cotização de uma coleção")
        print("  0. Sair")
        escolha = input("Escolha uma opção: ").strip()
        if escolha == "0":
            return
        acao = acoes.get(escolha)
        if acao is None:
            print("Opção inválida.")
            continue
        try:
            acao()
        except KeyboardInterrupt:
            print("\nOperação cancelada pelo usuário.")
        except Exception as erro:
            print(f"\nErro: {erro}")
        input("\nPressione ENTER para voltar ao menu...")


if __name__ == "__main__":
    main()
