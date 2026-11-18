import difflib
import json
import os
import re
import smtplib
import tempfile
import unicodedata
from datetime import datetime
from email.message import EmailMessage
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pyautogui
from PIL import ImageEnhance, ImageOps
from pynput import mouse


# =========================
# CONFIGURAÇÃO DO GMAIL
# =========================

EMAIL_REMETENTE = "VaultTcg0@gmail.com"

EMAIL_DESTINOS = [
    "hellonathzinha@gmail.com",
    "euleonsoto@gmail.com",
    "suriane@gmail.com"
]

# Configure VAULT_GMAIL_APP_PASSWORD no ambiente, sem publicar a senha no GitHub.
APP_PASSWORD = "".join(os.getenv("VAULT_GMAIL_APP_PASSWORD", "").split())


# =========================
# ESTADO DO PROGRAMA
# =========================

posicao_1 = None
enviando = False


def normalizar(texto):
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(letra for letra in texto if not unicodedata.combining(letra))
    return re.sub(r"[^a-z0-9]+", " ", texto.lower()).strip()


def consultar_cartas(consulta):
    parametros = urlencode({
        "q": consulta,
        "pageSize": 100,
        "select": "id,name,number,rarity,hp,types,set"
    })
    requisicao = Request(
        "https://api.pokemontcg.io/v2/cards?" + parametros,
        headers={"User-Agent": "VaultTCG-CardReader/1.0"},
    )
    chave_api = os.getenv("POKEMONTCG_API_KEY", "").strip()
    if chave_api:
        requisicao.add_header("X-Api-Key", chave_api)

    with urlopen(requisicao, timeout=12) as resposta:
        return json.load(resposta).get("data", [])


def identificar_carta(imagem):
    """Tenta reconhecer a carta via OCR e consultar os dados no Pokémon TCG."""
    try:
        import pytesseract
    except ImportError as erro:
        raise RuntimeError("Instale pytesseract para identificar cartas.") from erro

    comando_tesseract = os.getenv("TESSERACT_CMD", "").strip()
    if comando_tesseract:
        pytesseract.pytesseract.tesseract_cmd = comando_tesseract

    imagem = imagem.convert("RGB")
    largura, altura = imagem.size
    if largura < 80 or altura < 100:
        raise ValueError("A área selecionada é pequena demais para ler uma carta.")

    topo = imagem.crop((0, 0, largura, max(1, int(altura * 0.28))))
    topo = ImageEnhance.Contrast(ImageOps.grayscale(topo)).enhance(2.0)
    completa = ImageEnhance.Contrast(ImageOps.grayscale(imagem)).enhance(1.6)

    texto_topo = pytesseract.image_to_string(topo, config="--psm 6")
    texto_completo = pytesseract.image_to_string(completa, config="--psm 11")
    linhas = [linha.strip() for linha in texto_topo.splitlines() if linha.strip()]
    linhas += [linha.strip() for linha in texto_completo.splitlines() if linha.strip()]

    if not linhas:
        raise ValueError("Nenhum texto de carta foi reconhecido.")

    numero = None
    total = None
    correspondencia = re.search(r"(?<!\d)(\d{1,3})\s*/\s*(\d{2,3})(?!\d)", texto_completo)
    if correspondencia:
        numero = str(int(correspondencia.group(1)))
        total = int(correspondencia.group(2))

    nomes = []
    for linha in linhas[:12]:
        linha = re.sub(r"\b(?:BASIC|STAGE\s*[12]|POK[EÉ]MON)\b", " ", linha, flags=re.I)
        linha = re.sub(r"\bHP\s*\d+\b", " ", linha, flags=re.I)
        linha = re.sub(r"[^A-Za-zÀ-ÿ0-9' -]", " ", linha).strip()
        if (
            3 <= len(linha) <= 28
            and re.search(r"[A-Za-zÀ-ÿ]{3}", linha)
            and not re.search(r"\b(?:weakness|retreat|resistance|illustrator)\b", linha, re.I)
        ):
            nomes.append(linha)

    candidatos = []
    if numero:
        candidatos = consultar_cartas(f'number:"{numero}"')
    elif nomes:
        primeiro_nome = re.sub(r'[^a-zA-Z0-9 -]', '', nomes[0]).strip()
        if primeiro_nome:
            candidatos = consultar_cartas(f'name:"{primeiro_nome}"')

    if not candidatos:
        raise ValueError("Não foi possível localizar a carta na base Pokémon TCG.")

    melhor = None
    melhor_nota = 0.0
    texto_normalizado = normalizar(texto_topo)
    for carta in candidatos:
        nome_oficial = normalizar(carta.get("name", ""))
        if not nome_oficial:
            continue

        nota = max(
            [difflib.SequenceMatcher(None, nome_oficial, normalizar(nome)).ratio()
             for nome in nomes] or [0.0]
        )
        if nome_oficial in texto_normalizado:
            nota = max(nota, 0.95)

        conjunto = carta.get("set") or {}
        total_oficial = conjunto.get("printedTotal")
        if numero and str(carta.get("number", "")) == numero:
            nota += 0.10
        if total is not None and str(total_oficial) == str(total):
            nota += 0.35
        elif total is not None:
            nota -= 0.30

        if nota > melhor_nota:
            melhor = carta
            melhor_nota = nota

    if melhor is None or melhor_nota < 0.65:
        raise ValueError("Não foi possível identificar a carta com confiança.")

    return {
        "nome": melhor.get("name", "Não informado"),
        "colecao": (melhor.get("set") or {}).get("name", "Não informada"),
        "numero": melhor.get("number", "Não informado"),
        "raridade": melhor.get("rarity", "Não informada"),
        "hp": melhor.get("hp") or "Não informado",
        "tipos": ", ".join(melhor.get("types") or []) or "Não informados",
        "id": melhor.get("id", "Não informado"),
        "texto_reconhecido": texto_completo.strip()[:1200],
    }


def enviar_imagem_por_email(caminho_imagem, carta):
    """Envia a imagem selecionada com as informações reconhecidas da carta."""
    msg = EmailMessage()
    msg["From"] = EMAIL_REMETENTE
    msg["To"] = ", ".join(EMAIL_DESTINOS)
    msg["Subject"] = f"Captura Vault TCG - {datetime.now():%d/%m/%Y %H:%M:%S}"
    msg.set_content(
        "Captura de tela gerada automaticamente pelo script.\n\n"
        "Informações da carta Pokémon identificada:\n"
        f"Nome: {carta['nome']}\n"
        f"Coleção: {carta['colecao']}\n"
        f"Número: {carta['numero']}\n"
        f"Raridade: {carta['raridade']}\n"
        f"HP: {carta['hp']}\n"
        f"Tipo(s): {carta['tipos']}\n"
        f"ID na base: {carta['id']}\n\n"
        f"Texto detectado:\n{carta['texto_reconhecido']}\n"
    )

    with open(caminho_imagem, "rb") as arquivo:
        dados = arquivo.read()

    msg.add_attachment(
        dados,
        maintype="image",
        subtype="png",
        filename=os.path.basename(caminho_imagem),
    )

    if not APP_PASSWORD:
        raise RuntimeError("Defina VAULT_GMAIL_APP_PASSWORD antes do envio.")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as servidor:
        servidor.login(EMAIL_REMETENTE, APP_PASSWORD)
        servidor.send_message(msg)


def capturar_area(p1, p2):
    """Captura a área retangular formada por dois pontos."""
    x1, y1 = p1
    x2, y2 = p2

    esquerda = min(x1, x2)
    topo = min(y1, y2)
    direita = max(x1, x2)
    baixo = max(y1, y2)

    largura = direita - esquerda
    altura = baixo - topo

    if largura <= 0 or altura <= 0:
        raise ValueError("A área selecionada precisa ter largura e altura maiores que zero.")

    return pyautogui.screenshot(
        region=(esquerda, topo, largura, altura)
    )


def on_click(x, y, button, pressed):
    global posicao_1, enviando

    if not pressed:
        return

    if enviando:
        return

    if button == mouse.Button.left:
        posicao_1 = (x, y)
        print(f"[POSIÇÃO 1] x={x}, y={y}")
        print("Agora clique com o botão DIREITO para marcar a posição 2.")

    elif button == mouse.Button.right:
        if posicao_1 is None:
            print("Primeiro clique com o botão ESQUERDO para marcar a posição 1.")
            return

        posicao_2 = (x, y)
        print(f"[POSIÇÃO 2] x={x}, y={y}")

        enviando = True
        caminho = None

        try:
            imagem = capturar_area(posicao_1, posicao_2)

            nome = f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
            caminho = os.path.join(tempfile.gettempdir(), nome)

            imagem.save(caminho)

            print(f"[CAPTURA] Imagem salva temporariamente em: {caminho}")
            carta = identificar_carta(imagem)
            print("[EMAIL] Enviando...")

            enviar_imagem_por_email(caminho, carta)

            print("[OK] Imagem enviada para: " + ", ".join(EMAIL_DESTINOS))

        except Exception as erro:
            print(f"[ERRO] {erro}")

        finally:
            if caminho:
                try:
                    os.remove(caminho)
                except OSError:
                    pass
            posicao_1 = None
            enviando = False
            print("\nPronto para uma nova captura.")
            print("Clique ESQUERDO = posição 1 | Clique DIREITO = posição 2\n")


def main():
    print("=" * 60)
    print("CAPTURA DE ÁREA + ENVIO POR GMAIL")
    print("=" * 60)
    print("Clique ESQUERDO para marcar a posição 1.")
    print("Depois clique DIREITO para marcar a posição 2.")
    print("A área entre os dois pontos será capturada e enviada.")
    print("Destinos:")
    for email in EMAIL_DESTINOS:
        print(" -", email)
    print("Para encerrar, feche esta janela ou pressione Ctrl+C.")
    print("=" * 60)

    try:
        with mouse.Listener(on_click=on_click) as listener:
            listener.join()
    except KeyboardInterrupt:
        print("\nPrograma encerrado.")


if __name__ == "__main__":
    main()
