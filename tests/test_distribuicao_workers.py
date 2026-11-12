from src.shared.distribuicao_workers import distribuir_workers


def _cedentes(*ids):
    return [{"ID_CEDENTE": i} for i in ids]


def test_sem_cedentes_ou_sem_workers_retorna_vazio():
    assert distribuir_workers(cedentes=[], max_works=10, pesos_cedentes={}) == {}
    assert distribuir_workers(cedentes=_cedentes(1), max_works=0, pesos_cedentes={}) == {}


def test_usa_todos_os_workers_disponiveis():
    resultado = distribuir_workers(cedentes=_cedentes(1, 2, 3), max_works=10, pesos_cedentes={})
    assert sum(resultado.values()) == 10
    assert set(resultado) == {1, 2, 3}


def test_peso_da_mais_workers_ao_cedente():
    resultado = distribuir_workers(cedentes=_cedentes(1, 2, 3), max_works=10, pesos_cedentes={1: 2})
    assert resultado == {1: 5, 2: 3, 3: 2}


def test_menos_workers_que_cedentes_prioriza_maior_peso():
    resultado = distribuir_workers(cedentes=_cedentes(1, 2, 3), max_works=2, pesos_cedentes={3: 5})
    assert resultado == {3: 1, 1: 1}
