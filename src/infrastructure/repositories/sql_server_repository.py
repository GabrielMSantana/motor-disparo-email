"""Fila de disparo no SQL Server.

O ponto central é `reservar_lote_envio`: um único comando que SELECIONA e
MARCA o lote como PROCESSANDO de forma atômica.

    WITH (UPDLOCK, READPAST, ROWLOCK)

- UPDLOCK: trava as linhas lidas para atualização, então ninguém mais reserva as mesmas.
- READPAST: pula linhas já travadas por outro worker/processo, em vez de esperar.
- ROWLOCK: trava por linha, não a página/tabela inteira.

Resultado: vários workers (e até várias instâncias do robô) consomem a mesma
tabela em paralelo sem reenviar e-mail duplicado e sem fila de espera por lock.
"""
from typing import Any, Dict, List

from src.domain.status import Canal, Status
from src.infrastructure.database.sql_server_connection import SQLServerConnection
from src.shared.config import ConfigBanco, carregar_config_banco

_COLUNAS = [
    "ID", "ID_CLIENTE", "ID_CEDENTE", "NM_CARTEIRA", "GRUPO", "CANAL",
    "EMAIL_CLIENTE", "EMAIL_EMPRESA", "ID_TEMPLATE", "VARIAVEIS_JSON", "STATUS",
]


class RepositorioFilaSQLServer:
    """Mesma tabela para os dois canais. Muda apenas o filtro de CANAL."""

    def __init__(self, canal: Canal, config: ConfigBanco | None = None, conexao: SQLServerConnection | None = None):
        config = config or carregar_config_banco()
        self.sql = conexao or SQLServerConnection(config)
        self.tabela = config.tabela
        self.canal = canal
        # Ação = tudo que não é preventivo; Preventivo = só preventivo
        self._filtro_canal = "CANAL = 'PREVENTIVO'" if canal == Canal.PREVENTIVO else "CANAL <> 'PREVENTIVO'"
        self._filtro_pendente_hoje = f"""
                          {self._filtro_canal}
                      AND STATUS = '{Status.PENDENTE}'
                      AND ID_TEMPLATE IS NOT NULL
                      AND LTRIM(RTRIM(ID_TEMPLATE)) <> ''
                      AND CAST(DT_INCLUSAO AS DATE) = CAST(GETDATE() AS DATE)"""

    def obter_cedentes(self) -> List[Dict[str, Any]] | None:
        query = f"""
                    SELECT ID_CEDENTE
                    FROM {self.tabela} WITH (NOLOCK)
                    WHERE {self._filtro_pendente_hoje}
                    GROUP BY ID_CEDENTE
                """
        return self.sql.execute_fetch(query=query, parametros=(), one=False)

    def reservar_lote_envio(self, limite: int, id_cedente: int) -> List[Dict[str, Any]] | None:
        colunas = ", ".join(f"[{c}]" for c in _COLUNAS)
        saida = ", ".join(f"INSERTED.[{c}]" for c in _COLUNAS)
        query = f"""
                    ;WITH lote AS (
                        SELECT TOP (?) {colunas}
                        FROM {self.tabela} WITH (UPDLOCK, READPAST, ROWLOCK)
                        WHERE {self._filtro_pendente_hoje}
                          AND ID_CEDENTE = ?
                        ORDER BY ID
                    )
                    UPDATE lote
                       SET STATUS = '{Status.PROCESSANDO}'
                    OUTPUT {saida};
                """
        return self.sql.execute_fetch_commit(query=query, parametros=(limite, id_cedente), one=False)

    def atualizar_status_lote(self, atualizacoes: List[Dict[str, Any]]) -> int:
        """Atualiza N registros num único UPDATE usando uma tabela VALUES em linha."""
        if not atualizacoes:
            return 0

        valores = ",".join(["(?, ?)"] * len(atualizacoes))
        parametros: list = []
        for item in atualizacoes:
            parametros.extend((item["ID"], item["STATUS"]))

        query = f"""
                    UPDATE alvo
                       SET alvo.STATUS = dados.STATUS
                          ,alvo.DT_ENVIO = GETDATE()
                    OUTPUT INSERTED.ID, INSERTED.STATUS
                    FROM {self.tabela} AS alvo
                    INNER JOIN (VALUES {valores}) AS dados (ID, STATUS)
                        ON alvo.ID = dados.ID
                """
        registros = self.sql.execute_fetch_commit(query=query, parametros=tuple(parametros), one=False) or []
        return len(registros)

    def resetar_processando_antigo(self, minutos: int) -> int:
        """Devolve para PENDENTE os casos de hoje que ficaram presos em
        PROCESSANDO por causa de uma execução anterior que caiu no meio."""
        query = f"""
                    UPDATE {self.tabela}
                       SET STATUS = '{Status.PENDENTE}'
                     WHERE STATUS = '{Status.PROCESSANDO}'
                       AND {self._filtro_canal}
                       AND CAST(DT_INCLUSAO AS DATE) = CAST(GETDATE() AS DATE)
                       AND DT_INCLUSAO <= DATEADD(MINUTE, -?, GETDATE())
                """
        return self.sql.execute_commit(query=query, parametros=(minutos,)) or 0


def criar_repositorio(canal: Canal) -> RepositorioFilaSQLServer:
    return RepositorioFilaSQLServer(canal)
