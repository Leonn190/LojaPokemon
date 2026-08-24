import os
import smtplib
import tempfile
from datetime import datetime
from email.message import EmailMessage

import pyautogui
from pynput import mouse


# =========================
# CONFIGURAÇÃO DO GMAIL
# =========================

EMAIL_REMETENTE = "VaultTcg0@gmail.com"

EMAIL_DESTINOS = [
    "hallonathzinha@gmail.com",
    "suriane@gmail.com",
]

# Placeholder informado.
APP_PASSWORD_RAW = "aryd\u00a0uqik\u00a0xmct\u00a0wvqs"

# Remove espaços normais e espaços especiais antes do login SMTP.
APP_PASSWORD = "".join(APP_PASSWORD_RAW.split())


# =========================
# ESTADO DO PROGRAMA
# =========================

posicao_1 = None
enviando = False


def enviar_imagem_por_email(caminho_imagem):
    """Envia a imagem anexada para os e-mails configurados."""
    msg = EmailMessage()
    msg["From"] = EMAIL_REMETENTE
    msg["To"] = ", ".join(EMAIL_DESTINOS)
    msg["Subject"] = f"Captura Vault TCG - {datetime.now():%d/%m/%Y %H:%M:%S}"
    msg.set_content("Captura de tela gerada automaticamente pelo script.")

    with open(caminho_imagem, "rb") as arquivo:
        dados = arquivo.read()

    msg.add_attachment(
        dados,
        maintype="image",
        subtype="png",
        filename=os.path.basename(caminho_imagem),
    )

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

        try:
            imagem = capturar_area(posicao_1, posicao_2)

            nome = f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
            caminho = os.path.join(tempfile.gettempdir(), nome)

            imagem.save(caminho)

            print(f"[CAPTURA] Imagem salva temporariamente em: {caminho}")
            print("[EMAIL] Enviando...")

            enviar_imagem_por_email(caminho)

            print("[OK] Imagem enviada para: " + ", ".join(EMAIL_DESTINOS))

            try:
                os.remove(caminho)
            except OSError:
                pass

        except Exception as erro:
            print(f"[ERRO] {erro}")

        finally:
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
