import threading
from typing import Dict, List, Tuple

from src.shared.config import ConfigBanco
from src.shared.log_config import obter_logger

log = obter_logger()


# SQLSTATEs que indicam CONEXÃO PERDIDA (servidor fechou por ociosidade, link
# caiu etc.). Só nesses casos vale descartar a conexão reutilizada e tentar UMA
# vez com uma conexão nova. Erros normais (deadlock, sintaxe...) não entram aqui.
_SQLSTATES_CONEXAO = ("08S01", "08001", "08002", "08003", "08004", "08007", "HYT00", "HYT01")


class SQLServerConnection:
    """Conexão com SQL Server via pyodbc.

    Reaproveita UMA conexão POR THREAD (thread-local). Como os envios rodam em
    várias threads (asyncio.to_thread), cada thread mantém a sua conexão e a
    reutiliza em muitas queries, em vez de abrir/fechar uma conexão a cada query.
    Isso elimina milhares de handshakes (TCP + login + TLS) por execução.

    pyodbc não é thread-safe por conexão, por isso cada thread tem a SUA (nunca
    é compartilhada). Em erro de conexão perdida, a conexão é descartada e a
    operação é tentada novamente uma única vez com uma conexão nova.
    """

    def __init__(self, config: ConfigBanco):
        import pyodbc  # import tardio: demo e testes não precisam do driver ODBC

        self._pyodbc = pyodbc
        self._config = config
        # Guarda a conexão por thread. Cada thread enxerga apenas a sua.
        self._local = threading.local()

    def _connect(self):
        return self._pyodbc.connect(
            f"DRIVER={{{self._config.driver}}};"
            f"SERVER={self._config.servidor};"
            f"DATABASE={self._config.banco};"
            f"UID={self._config.usuario};"
            f"PWD={self._config.senha};"
            "TrustServerCertificate=YES"
        )

    def _obter_conexao(self):
        """Retorna a conexão da thread atual, criando-a na primeira vez."""
        conexao = getattr(self._local, "conexao", None)
        if conexao is None:
            conexao = self._connect()
            self._local.conexao = conexao
        return conexao

    def _descartar_conexao(self) -> None:
        """Fecha e esquece a conexão da thread atual (ex.: após erro).
        A próxima operação daquela thread abrirá uma conexão nova e limpa."""
        conexao = getattr(self._local, "conexao", None)
        self._local.conexao = None
        if conexao is not None:
            try:
                conexao.close()
            except Exception:
                pass

    @staticmethod
    def eh_erro_conexao(erro: Exception) -> bool:
        """True quando o erro indica conexão perdida (vale reconectar e tentar 1x)."""
        sqlstate = ""
        args = getattr(erro, "args", None)
        if args:
            sqlstate = str(args[0])
        texto = f"{sqlstate} {erro}".lower()
        return (
            sqlstate in _SQLSTATES_CONEXAO
            or sqlstate.startswith("08")
            or "communication link failure" in texto
            or "connection is closed" in texto
            or "not connected" in texto
        )

    def _executar(self, query: str, parametros, *, commit: bool, buscar: bool, one: bool):
        """Executa com reconexão automática (1 nova tentativa) em queda de conexão."""
        for tentativa in range(2):
            try:
                conexao = self._obter_conexao()

                with conexao.cursor() as cursor:
                    cursor.execute(query, parametros)

                    resultado = None
                    if buscar:
                        colunas = [c[0] for c in cursor.description] if cursor.description else []
                        linhas = cursor.fetchone() if one else cursor.fetchall()

                        if linhas and one:
                            resultado = dict(zip(colunas, linhas))
                        elif linhas:
                            resultado = [dict(zip(colunas, linha)) for linha in linhas]
                    else:
                        resultado = cursor.rowcount

                    if commit:
                        conexao.commit()

                    return resultado

            except self._pyodbc.Error as erro:
                reconectavel = self.eh_erro_conexao(erro)
                self._descartar_conexao()
                if reconectavel and tentativa == 0:
                    continue
                log.error(f"Erro no banco: {erro}")
                return None

    def execute_fetch(self, *, query: str, parametros: Tuple | List[Tuple], one: bool = False) -> List[Dict] | Dict | None:
        return self._executar(query, parametros, commit=False, buscar=True, one=one)

    def execute_fetch_commit(self, *, query: str, parametros: Tuple | List[Tuple], one: bool = False) -> List[Dict] | Dict | None:
        return self._executar(query, parametros, commit=True, buscar=True, one=one)

    def execute_commit(self, *, query: str, parametros: Tuple) -> int | None:
        return self._executar(query, parametros, commit=True, buscar=False, one=False)
