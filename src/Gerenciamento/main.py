from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from typing import TypeVar

T = TypeVar("T")


def garantir_dependencias() -> None:
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
    print("\nQual valor deve preencher o campo Preço?")
    print("  1. Menor preço encontrado/estimado na Liga")
    print("  2. Média das ofertas encontradas/estimadas da Liga")
    while True:
        resposta = input("Escolha 1 ou 2: ").strip()
        if resposta == "1": return "menor"
        if resposta == "2": return "media"
        print("Escolha somente 1 ou 2.")


def executar_formatacao() -> None:
    from configuracao import ARQUIVO_PERFIL
    from gerenciamento import formatar_nova_colecao, listar_pacotes
    pacote = escolher("Coleções não formatadas disponíveis", listar_pacotes(ARQUIVO_PERFIL), lambda item: item.name)
    destino = formatar_nova_colecao(pacote, escolher_modo_preco())
    import json
    perfil = json.loads((destino / "perfil.json").read_text(encoding="utf-8"))
    if perfil.get("formattingComplete") is False:
        print(f"\nFormatação salva parcialmente em:\n{destino}")
        print(f"Ainda existem {int(perfil.get('formattingPending') or 0)} item(ns) pendente(s). Execute novamente para retomar.")
    else:
        print(f"\nColeção formatada em:\n{destino}")
        print("Inventários salvos no novo formato JSON.")


def executar_atualizacao() -> None:
    from configuracao import ARQUIVO_ATUALIZACAO
    from gerenciamento import atualizar_colecao, listar_pacotes
    pacote = escolher("Atualizações disponíveis", listar_pacotes(ARQUIVO_ATUALIZACAO), lambda item: item.name)
    destino = atualizar_colecao(pacote)
    print(f"\nAtualização aplicada integralmente em:\n{destino}")


def escolher_escopo() -> tuple[str, int | None]:
    print("\nO que deseja cotizar?")
    print("  1. Coleção inteira")
    print("  2. Apenas cartas")
    print("  3. Apenas boosters")
    print("  4. Apenas itens à venda")
    print("  5. Apenas itens sem preço")
    print("  6. Apenas itens não atualizados há X dias")
    while True:
        opcao = input("Escolha 1 a 6: ").strip()
        if opcao in {"1", "2", "3", "4", "5"}:
            return opcao, None
        if opcao == "6":
            while True:
                try:
                    dias = int(input("Há quantos dias sem cotização? ").strip())
                    if dias > 0:
                        return opcao, dias
                except ValueError:
                    pass
                print("Digite um número inteiro maior que zero.")
        print("Escolha uma opção de 1 a 6.")


def executar_cotizacao() -> None:
    from gerenciamento import cotizacao_pendente, cotizar_colecao, listar_colecoes
    colecao = escolher("Coleções disponíveis para cotização", listar_colecoes(), lambda item: item.name)
    if cotizacao_pendente(colecao):
        print("\nExiste uma cotização incompleta salva para esta coleção.")
        while True:
            resposta = input("Continuar de onde parou? [S/N]: ").strip().upper()
            if resposta in {"S", "SIM"}:
                destino = cotizar_colecao(colecao, retomar=True)
                break
            if resposta in {"N", "NAO", "NÃO"}:
                # Uma nova sessão substitui apenas o arquivo de progresso; os preços já salvos continuam no histórico.
                (colecao / "cotizacao-em-andamento.json").unlink(missing_ok=True)
                opcao, dias = escolher_escopo()
                destino = cotizar_colecao(colecao, opcao=opcao, dias=dias, retomar=False)
                break
            print("Responda S ou N.")
    else:
        opcao, dias = escolher_escopo()
        destino = cotizar_colecao(colecao, opcao=opcao, dias=dias)
    if cotizacao_pendente(destino):
        print(f"\nCotização salva parcialmente em:\n{destino}")
        print("Existem itens pendentes; execute a cotização novamente para retomar somente o que falhou.")
    else:
        print(f"\nCotização concluída em:\n{destino}")
        print(f"Relatórios detalhados: {destino / 'relatorios'}")


def main() -> None:
    garantir_dependencias()
    acoes = {"1": executar_formatacao, "2": executar_atualizacao, "3": executar_cotizacao}
    while True:
        print("\n" + "=" * 62)
        print("NEXUS TCG — GERENCIAMENTO DE COLEÇÕES")
        print("=" * 62)
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
            print("\nOperação interrompida. Se era formatação/cotização, o progresso parcial foi preservado.")
        except Exception as erro:
            print(f"\nErro: {erro}")
        input("\nPressione ENTER para voltar ao menu...")


if __name__ == "__main__":
    main()
