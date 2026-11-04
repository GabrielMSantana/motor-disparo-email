def distribuir_workers(*, cedentes: list, max_works: int, pesos_cedentes: dict) -> dict:
    """Divide um total fixo de workers entre os cedentes com envio pendente.

    Regras, nesta ordem:
    1. Todo cedente ativo recebe pelo menos 1 worker (enquanto houver workers).
       Cedentes com maior peso vêm primeiro.
    2. O peso vira bônus, entregue +1 por rodada, para não "estourar" num só.
    3. O que sobrar é distribuído em round-robin, usando toda a capacidade.

    Exemplo: 10 workers, cedentes {1: peso 2, 2: peso 0, 3: peso 0}
        -> {1: 5, 2: 3, 3: 2}
    """
    if not cedentes or max_works <= 0:
        return {}

    cedentes_ordenados = sorted(
        cedentes,
        key=lambda item: (-pesos_cedentes.get(item["ID_CEDENTE"], 0), item["ID_CEDENTE"]),
    )

    distribuicao = {item["ID_CEDENTE"]: 0 for item in cedentes_ordenados}

    # Garante pelo menos 1 worker por cedente ativo, respeitando o total disponível.
    for item in cedentes_ordenados[:max_works]:
        distribuicao[item["ID_CEDENTE"]] = 1

    restantes = max_works - sum(distribuicao.values())
    if restantes <= 0:
        return {cedente: qtd for cedente, qtd in distribuicao.items() if qtd > 0}

    cedentes_ativos = [
        item for item in cedentes_ordenados
        if distribuicao[item["ID_CEDENTE"]] > 0
    ]

    # Aplica o peso aos poucos: cada rodada entrega apenas +1 por vez.
    max_bonus = max((max(0, pesos_cedentes.get(item["ID_CEDENTE"], 0)) for item in cedentes_ativos), default=0)
    for nivel_bonus in range(max_bonus):
        for item in cedentes_ativos:
            if restantes <= 0:
                break

            bonus = max(0, pesos_cedentes.get(item["ID_CEDENTE"], 0))
            if bonus > nivel_bonus:
                distribuicao[item["ID_CEDENTE"]] += 1
                restantes -= 1

        if restantes <= 0:
            break

    # Usa qualquer worker restante em round-robin para consumir toda a capacidade.
    while restantes > 0:
        for item in cedentes_ativos:
            if restantes <= 0:
                break

            distribuicao[item["ID_CEDENTE"]] += 1
            restantes -= 1

    return {cedente: qtd for cedente, qtd in distribuicao.items() if qtd > 0}
