"""Leitura de configuração a partir de variáveis de ambiente (.env).

As variáveis só são exigidas quando o recurso é usado de fato. Assim o modo
demo e os testes rodam sem banco nem chave da SendGrid configurados.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def obter_env_obrigatoria(nome: str) -> str:
    valor = os.getenv(nome)
    if valor is None or valor.strip() == "":
        raise ValueError(f"A variável de ambiente '{nome}' não foi definida.")
    return valor


@dataclass(frozen=True)
class ConfigBanco:
    servidor: str
    banco: str
    usuario: str
    senha: str
    driver: str
    tabela: str


@dataclass(frozen=True)
class ConfigSendGrid:
    api_key: str
    copia_oculta: str | None


def carregar_config_banco() -> ConfigBanco:
    return ConfigBanco(
        servidor=obter_env_obrigatoria("DB_SERVER"),
        banco=obter_env_obrigatoria("DB_NAME"),
        usuario=obter_env_obrigatoria("DB_USER"),
        senha=obter_env_obrigatoria("DB_PASSWORD"),
        driver=os.getenv("DB_DRIVER", "ODBC Driver 17 for SQL Server"),
        tabela=os.getenv("DB_TABELA_FILA", "[email].[TB_FILA_DISPARO]"),
    )


def carregar_config_sendgrid() -> ConfigSendGrid:
    return ConfigSendGrid(
        api_key=obter_env_obrigatoria("SENDGRID_API_KEY"),
        copia_oculta=os.getenv("COPIA_OCULTA") or None,
    )
