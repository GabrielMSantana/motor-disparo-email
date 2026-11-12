from concurrent.futures import ThreadPoolExecutor

from src.domain.status import Canal, Status
from src.infrastructure.repositories.memoria_repository import RepositorioFilaMemoria


def test_reserva_concorrente_nunca_entrega_o_mesmo_registro(fabrica_registro):
    repo = RepositorioFilaMemoria([fabrica_registro(i) for i in range(1, 1001)], Canal.ACAO)

    def reservar_tudo():
        ids = []
        while lote := repo.reservar_lote_envio(7, 1):
            ids.extend(r["ID"] for r in lote)
        return ids

    with ThreadPoolExecutor(max_workers=16) as pool:
        resultados = list(pool.map(lambda _: reservar_tudo(), range(16)))

    todos = [i for ids in resultados for i in ids]
    assert len(todos) == 1000
    assert len(set(todos)) == 1000  # nenhum ID reservado duas vezes


def test_filtra_por_canal(fabrica_registro):
    registros = [fabrica_registro(1, canal="PREVENTIVO"), fabrica_registro(2, canal="EMAIL")]

    acao = RepositorioFilaMemoria([dict(r) for r in registros], Canal.ACAO)
    preventivo = RepositorioFilaMemoria([dict(r) for r in registros], Canal.PREVENTIVO)

    assert [r["ID"] for r in acao.reservar_lote_envio(10, 1)] == [2]
    assert [r["ID"] for r in preventivo.reservar_lote_envio(10, 1)] == [1]


def test_ignora_registro_sem_template(fabrica_registro):
    repo = RepositorioFilaMemoria([fabrica_registro(1, template="  ")], Canal.ACAO)
    assert repo.obter_cedentes() == []
    assert repo.reservar_lote_envio(10, 1) == []


def test_reset_devolve_apenas_processando_antigo(fabrica_registro):
    repo = RepositorioFilaMemoria(
        [
            fabrica_registro(1, status=Status.PROCESSANDO, minutos_atras=60),
            fabrica_registro(2, status=Status.PROCESSANDO, minutos_atras=1),
            fabrica_registro(3, status=Status.SUCESSO, minutos_atras=60),
        ],
        Canal.ACAO,
    )

    assert repo.resetar_processando_antigo(30) == 1
    assert repo.obter(1)["STATUS"] == Status.PENDENTE
    assert repo.obter(2)["STATUS"] == Status.PROCESSANDO
    assert repo.obter(3)["STATUS"] == Status.SUCESSO
