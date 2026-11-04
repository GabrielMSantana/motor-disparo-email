"""Configuração de log em arquivo com rotação diária.

Regra de retenção: 1 arquivo por dia, mantendo 6 no total (o do dia atual + 5
dos dias anteriores = 1 semana). À meia-noite, o arquivo do dia vira um backup
datado e o mais antigo é apagado (TimedRotatingFileHandler com backupCount=5).

Como ação e preventivo são processos separados (podem rodar juntos), cada
fluxo grava no SEU arquivo, evitando conflito de rotação entre processos no Windows.
"""
import logging
import os
from logging.handlers import TimedRotatingFileHandler

NOME_LOGGER = "motor_disparo_email"

# Mantém o do dia + 5 anteriores = 6 arquivos no total (1 semana).
_QTD_BACKUPS = 5


def obter_logger() -> logging.Logger:
    """Devolve o logger do projeto. Use no topo de cada módulo:
        log = obter_logger()
    Os handlers são anexados uma única vez por configurar_log() no início."""
    return logging.getLogger(NOME_LOGGER)


def _raiz_projeto() -> str:
    # .../src/shared/log_config.py -> sobe até a raiz do projeto
    atual = os.path.abspath(__file__)
    for _ in range(3):
        atual = os.path.dirname(atual)
    return atual


def configurar_log(nome_arquivo: str | None) -> logging.Logger:
    """Configura (uma vez) o logger para gravar em arquivo com rotação diária e
    também exibir no terminal. Com `nome_arquivo=None`, loga só no terminal.
    Idempotente: chamar de novo não duplica handlers."""
    logger = logging.getLogger(NOME_LOGGER)

    if getattr(logger, "_configurado", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    formato = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if nome_arquivo:
        # Pasta dos logs: usa LOG_DIR do .env se existir; senão, <projeto>/logs.
        dir_logs = os.getenv("LOG_DIR") or os.path.join(_raiz_projeto(), "logs")
        os.makedirs(dir_logs, exist_ok=True)

        arquivo = TimedRotatingFileHandler(
            os.path.join(dir_logs, nome_arquivo),
            when="midnight",
            interval=1,
            backupCount=_QTD_BACKUPS,
            encoding="utf-8",
        )
        arquivo.suffix = "%Y-%m-%d"  # backups: envio_acao.log.2026-01-31
        arquivo.setFormatter(formato)
        logger.addHandler(arquivo)

    # Também mostra no terminal (quando roda na mão).
    console = logging.StreamHandler()
    console.setFormatter(formato)
    logger.addHandler(console)

    logger._configurado = True  # marca para não duplicar handlers
    return logger
