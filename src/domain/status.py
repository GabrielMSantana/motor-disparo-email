"""Estados e canais da fila de disparo.

Ciclo de vida de um registro:
    PENDENTE -> PROCESSANDO -> SUCESSO | ERRO | ERRO_BOLETO

PROCESSANDO funciona como "reserva": enquanto um worker segura o registro,
nenhum outro processo consegue pegá-lo. Se a execução cair no meio, um reset
devolve para PENDENTE os registros presos há mais de N minutos.
"""
from enum import Enum


class Status:
    PENDENTE = "PENDENTE"
    PROCESSANDO = "PROCESSANDO"
    SUCESSO = "SUCESSO"
    ERRO = "ERRO"
    ERRO_BOLETO = "ERRO ao baixar boleto"


class Canal(str, Enum):
    """Dois fluxos com o mesmo motor e filtros diferentes.

    - ACAO: cobrança/negociação (tudo que não é preventivo)
    - PREVENTIVO: lembrete antes do vencimento, normalmente com boleto
    """

    ACAO = "ACAO"
    PREVENTIVO = "PREVENTIVO"
