import threading
import time
from typing import Any, Callable, Dict

import requests
from requests.adapters import HTTPAdapter
from sendgrid.helpers.mail import Attachment, Bcc, CustomArg, Email, Mail, To

from src.shared.config import ConfigSendGrid, carregar_config_sendgrid

try:
    from sendgrid import __version__ as _SENDGRID_VERSION
except Exception:
    _SENDGRID_VERSION = "6"

# Mesmo endpoint que a SDK usa internamente (send() -> POST /v3/mail/send).
_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

# Sessão HTTP por thread (thread-local): cada thread reutiliza a SUA conexão com a
# SendGrid (keep-alive), em vez de abrir um handshake TLS novo a cada e-mail. Como
# os envios rodam em threads do pool (asyncio.to_thread), isso reduz milhares de
# handshakes para ~uma conexão por thread, sem compartilhar sessão entre threads.
_local = threading.local()


def _obter_sessao() -> requests.Session:
    sessao = getattr(_local, "sessao", None)
    if sessao is None:
        sessao = requests.Session()
        adaptador = HTTPAdapter(pool_connections=2, pool_maxsize=4)
        sessao.mount("https://", adaptador)
        _local.sessao = sessao
    return sessao


class SendGrid:
    """Envio por template dinâmico da SendGrid, com retry em erros transitórios.

    Usa a SDK só para montar o corpo (Mail) e faz o POST numa sessão HTTP
    reaproveitada. O corpo enviado é idêntico ao que a SDK mandaria.
    """

    CODIGOS_TRANSITORIOS = {429, 500, 502, 503, 504}

    def __init__(
        self,
        config: ConfigSendGrid | None = None,
        *,
        max_retries: int = 3,
        obter_sessao: Callable[[], requests.Session] = _obter_sessao,
        dormir: Callable[[float], None] = time.sleep,
    ):
        config = config or carregar_config_sendgrid()
        self._email_bcc = config.copia_oculta
        self._max_retries = max_retries
        self._obter_sessao = obter_sessao
        self._dormir = dormir
        self._headers = {
            "Authorization": f"Bearer {config.api_key}",
            "User-Agent": f"sendgrid/{_SENDGRID_VERSION};python",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def _adicionar_copia_oculta(self, msg: Mail) -> None:
        if self._email_bcc:
            msg.add_bcc(Bcc(self._email_bcc))

    @staticmethod
    def _tempo_espera(tentativa: int, retry_after: str | None) -> float:
        """Respeita o Retry-After do provedor quando vier; senão, espera crescente."""
        if retry_after and str(retry_after).isdigit():
            return max(1.0, float(retry_after))
        return max(1.0, float(tentativa))

    def _send_with_retry(self, msg: Mail) -> int:
        corpo = msg.get()
        sessao = self._obter_sessao()

        # Até `max_retries` tentativas para erros transitórios (429/5xx) e falhas de rede
        for tentativa in range(1, self._max_retries + 1):
            try:
                # timeout evita worker travado para sempre
                response = sessao.post(_SENDGRID_URL, json=corpo, headers=self._headers, timeout=30)
                status_code = int(response.status_code)

                if status_code not in self.CODIGOS_TRANSITORIOS or tentativa >= self._max_retries:
                    return status_code

                self._dormir(self._tempo_espera(tentativa, response.headers.get("Retry-After")))

            except requests.RequestException as erro:
                if tentativa >= self._max_retries:
                    raise RuntimeError("Falha ao enviar email via SendGrid") from erro

                self._dormir(float(tentativa))

        raise RuntimeError("Fluxo inesperado em _send_with_retry")

    def enviar_template(
        self,
        remetente: str,
        destinatario: str,
        template_id: str,
        variaveis: Dict[str, Any],
        anexo: Attachment | None = None,
        custom_args: Dict[str, Any] | None = None,
    ) -> int:
        msg = Mail(from_email=Email(remetente), to_emails=To(destinatario))
        msg.template_id = template_id
        msg.dynamic_template_data = variaveis

        if anexo:
            msg.attachment = anexo

        # Metadados que a SendGrid devolve no webhook (ex.: id_cedente, id_template)
        # para a API de monitoramento registrar. Ignora valores nulos/vazios.
        if custom_args:
            for chave, valor in custom_args.items():
                if valor is None or str(valor).strip() == "":
                    continue
                msg.add_custom_arg(CustomArg(str(chave), str(valor)))

        self._adicionar_copia_oculta(msg)

        return self._send_with_retry(msg)
