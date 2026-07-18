---
name: lojaeletrica-search
description: >
  Use esta skill para consultar preços e dados de produtos do site Loja Elétrica
  (lojaeletrica.com.br) a partir dos dados já coletados pelo scraper. Ela permite
  buscar por nome de produto, material, bitola/medida e categoria usando o CLI
  scripts/search.py. Use quando o usuário perguntar preços, buscar materiais
  elétricos, comparar produtos por bitola ou material, ou pedir links de produtos
  do site — mesmo que não diga "buscar" ou "search" explicitamente.
license: MIT
metadata:
  author: stgan
  version: "1.0"
---

# Consulta de produtos da Loja Elétrica

Busca rápida em dados já coletados pelo scraper, sem necessidade de acessar o
site novamente. Útil para cotações, comparações de preço e levantamento de
materiais elétricos.

**Failure pattern:** Criação repetida de scripts Python ad-hoc para cada consulta
de produto — cada busca exigia um novo script descartável com lógica de filtro
reimplementada do zero.

**Verified by:** 7 testes de aceite passaram: busca por produto (≥10 resultados),
filtro de material (apenas PVC), filtro de bitola (1" sem frações), filtros
combinados (11 resultados idênticos à busca manual), saída JSON válida, busca
sem resultados (exit 0, sem erro), e --help funcional.

## When to use this

- O usuário pergunta o preço de um material elétrico (eletroduto, cabo, abraçadeira, etc.)
- O usuário quer comparar produtos por bitola, material ou fabricante
- O usuário pede o link de um produto na Loja Elétrica
- O usuário quer listar opções disponíveis de um tipo de material

## Pré-requisitos

O arquivo `lojaeletrica_raw.json` deve existir na raiz do projeto. Ele é gerado
pelo scraper (`python scripts/lojaeletrica_scraper.py`). Sem ele, o search não
funciona.

## Procedure

- [ ] 1. Identificar os filtros a partir do pedido do usuário:
  - `--produto` / `-p`: nome ou tipo do produto (ex: "eletroduto", "cabo", "curva")
  - `--material` / `-m`: material (ex: "pvc", "aluminio", "galvanizado")
  - `--bitola` / `-b`: medida/bitola (ex: `1` para 1", `3/4` para 3/4", `1,5mm`)
  - `--categoria` / `-c`: categoria do site (ex: "Eletrodutos", "Cabos Elétricos")
- [ ] 2. Rodar o comando com os filtros apropriados:
```bash
python scripts/search.py --produto "eletroduto" --material "pvc" --bitola 1
```
- [ ] 3. Para saída em JSON (útil para processamento posterior):
```bash
python scripts/search.py --produto "cabo" --bitola 1,5mm --json
```
- [ ] 4. Para limitar resultados:
```bash
python scripts/search.py --produto "abraçadeira" --limit 5
```
- [ ] 5. Apresentar os resultados ao usuário em tabela com produto, preço e link.

### Example

```
$ python scripts/search.py -p "luva" -m "pvc" -b 1

🔍 3 resultado(s) encontrado(s) para: produto="luva", material="pvc", bitola="1"

#  │ Categoria    │ Produto                                       │ Preço (R$) │ Link
───┼──────────────┼───────────────────────────────────────────────┼────────────┼──────
1  │ Eletrodutos  │ Luva PVC com Rosca 1"                        │ R$ 0,66    │ https://...
2  │ Eletrodutos  │ Luva PVC Preta Com Rosca Antichamas 1" Krona │ R$ 2,04    │ https://...
3  │ Eletrodutos  │ Luva PVC Rosca Antichama 1" Tigre            │ R$ 3,30    │ https://...
```

## Gotchas

- **Bitola em polegadas no PowerShell:** O PowerShell remove as aspas duplas dos
  argumentos. Use apenas o número: `--bitola 1` ao invés de `--bitola '1"'`.
  O script detecta automaticamente e assume polegadas.
- **Bitola em milímetros:** Use vírgula ou ponto: `--bitola 1,5mm` ou `--bitola 1.5mm`.
  Ambos funcionam.
- **Produtos com preço R$ 0,00:** Aparecem no final da lista com marcação
  `⚠️ Indisponível`. Isso indica que o preço não foi capturado no scraping.
- **Busca por acentos:** A busca ignora acentos. `"abracadeira"` encontra
  `"Abraçadeira"` normalmente.
- **Dados desatualizados:** Os resultados vêm do `lojaeletrica_raw.json`. Se os
  preços do site mudaram, re-execute o scraper primeiro:
  `python scripts/lojaeletrica_scraper.py`

## What didn't work

- **Scripts ad-hoc por consulta:** Antes desta skill, cada busca exigia criar um
  script Python descartável com lógica de filtro personalizada. Além de lento,
  cada script reimplementava a lógica de filtragem de bitola (com os mesmos bugs
  de falsos positivos em frações). O CLI centralizado resolve isso.
- **Filtro de bitola com substring simples:** Buscar `1"` como substring casava
  com `1/2"`, `1.1/2"`, `1.1/4"`. Foi necessário usar regex com negative
  lookbehind (`(?<![.\d])`) e negative lookahead (`(?!/)`) para filtrar
  corretamente apenas a bitola exata.
