import base64
import re

import requests
from requests.adapters import HTTPAdapter
from sendgrid.helpers.mail import Attachment, Disposition, FileContent, FileName, FileType


class BoletoService:
    """Baixa o PDF do boleto e transforma em anexo de e-mail."""

    def __init__(self):
        # Sessão reutilizada: mantém keep-alive e evita abrir uma conexão TLS nova
        # a cada boleto. O pool é dimensionado para os vários workers do cedente
        # baixarem em paralelo sem ficar esperando conexão livre.
        self._session = requests.Session()
        adaptador = HTTPAdapter(pool_connections=10, pool_maxsize=64)
        self._session.mount("https://", adaptador)
        self._session.mount("http://", adaptador)

    @staticmethod
    def _gerar_nome_arquivo(nome: str) -> str:
        nome_limpo = re.sub(r"[^\w\s]", "", nome or "cliente").replace(" ", "_").lower()
        return f"{nome_limpo}_boleto.pdf"

    def _baixar_boleto(self, url: str) -> bytes:
        response = self._session.get(url, timeout=30)

        if response.status_code != 200:
            raise RuntimeError(f"Erro ao baixar boleto: {response.status_code}")

        return response.content

    def _gerar_anexo_por_conteudo(self, conteudo: bytes, nome_cliente: str) -> Attachment:
        conteudo_base64 = base64.b64encode(conteudo).decode()
        nome_arquivo = self._gerar_nome_arquivo(nome_cliente)

        return Attachment(
            FileContent(conteudo_base64),
            FileName(nome_arquivo),
            FileType("application/pdf"),
            Disposition("attachment"),
        )

    def gerar_anexo_por_url(self, url: str, nome_cliente: str) -> Attachment:
        conteudo = self._baixar_boleto(url)
        return self._gerar_anexo_por_conteudo(conteudo, nome_cliente)
