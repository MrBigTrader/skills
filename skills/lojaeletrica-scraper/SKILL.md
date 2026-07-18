---
name: lojaeletrica-scraper
description: >
  Use esta skill para entender, executar e expandir o scraper do site Loja Elétrica
  (lojaeletrica.com.br). Ela detalha as dependências necessárias, os comandos de
  inicialização do Playwright, as estruturas de saída de dados (JSON e Excel com
  resumo e formatação) e fornece um guia exato para manutenção e adição de novas
  categorias de produtos. Use sempre que for planejar alterações no scraper,
  adicionar categorias, depurar problemas de extração ou rodar coletas no site.
license: MIT
metadata:
  author: stgan
  version: "1.2"
---

# Loja Elétrica Scraper

Esta skill documenta o ecossistema do scraper da Loja Elétrica, permitindo a
extração de dados estruturados e de mercado para infraestrutura, conectores,
dispositivos de proteção e cabos elétricos.

**Failure pattern:** Erros de dependências não instaladas (como falta do navegador
Chromium no Playwright), loops infinitos de paginação quando seletores mudavam e
falta de documentação para adicionar categorias novas com URLs válidas.

**Verified by:** Execuções reais bem-sucedidas no Chromium headless, gerando planilhas
Excel estilizadas com abas de estatísticas e indexando dados em banco SQLite.

## Instalação e Configuração

### Pré-requisitos
O scraper exige Python 3.8+ e as seguintes dependências instaladas:
```bash
pip install playwright pandas openpyxl jinja2
```

### Inicialização do Playwright
Antes da primeira execução, é necessário baixar os binários do navegador Chromium:
```bash
playwright install chromium
```

## Estrutura do Projeto

*   `scripts/lojaeletrica_scraper.py`: Core do scraper, responsável por gerenciar a navegação do Playwright, extração de produtos das categorias e geração da planilha Excel formatada.
*   `scripts/run_scraper.bat`: Script em lote para rodar o scraper de forma simples pelo Windows.
*   `lojaeletrica_raw.json`: Arquivo JSON bruto gerado no final do scraping para consultas e cache local.
*   `lojaeletrica_historico.db`: Banco de dados SQLite contendo o histórico temporal de variação de preços.
*   `lojaeletrica_infraestrutura.xlsx`: Planilha final de cotações com formatação avançada.

## Como Executar

### 1. Execução Completa
Para varrer todas as 44 categorias cadastradas e atualizar os relatórios e o banco de dados:
```bash
# Via terminal
python scripts/lojaeletrica_scraper.py

# Via arquivo de lote (dois cliques no Windows)
scripts\run_scraper.bat
```

### 2. Automação Semanal
O scraper está configurado no Agendador de Tarefas do Windows para rodar automaticamente todos os domingos às 02:00. O nome da tarefa agendada é `LojaEletricaScraper` e ela executa o script `run_scraper.bat`.

## Estrutura e Lógicas de Extração

### Wait Inteligente com Fallback
Para evitar lentidão e esperas fixas desnecessárias, o scraper usa `page.wait_for_selector(".product-item", timeout=15000)` para detectar quando o JavaScript do Magento 2 terminou de carregar os produtos.
- Se os produtos renderizarem antes (geralmente leva 0.7s a 1.2s), a página avança imediatamente.
- Se der timeout (página lenta ou vazia), o scraper usa um fallback conservador de `asyncio.sleep(5)`.

### Retry para Preços Indisponíveis
Se o scraper encontrar um produto com preço R$ 0,00, ele aguarda **3 segundos adicionais** e tenta re-extrair.
- Produtos que permanecerem sem preço são marcados com `preco_disponivel: False` e exibidos com a string `"Indisponível"` no JSON.
- No Excel, esses itens ganham a flag `"Não"` na coluna `"Preço Disponível"`.
- Na busca local do CLI `search.py`, eles são marcados com a tag visual `⚠️ Indisponível`.

## Guia de Expansão: Como Adicionar Categorias

Para adicionar uma nova categoria à varredura do scraper:

1.  Acesse o site [lojaeletrica.com.br](https://www.lojaeletrica.com.br) e localize a categoria desejada no menu.
2.  Copie o link da categoria. A URL deve terminar com `.html` (ex: `.../infraestrutura-eletrica/eletrodutos.html`).
3.  Abra o arquivo `scripts/lojaeletrica_scraper.py`.
4.  Localize a constante global `CATEGORIES`.
5.  Adicione uma nova tupla contendo o nome descritivo que deseja dar à aba do Excel e a URL completa:
```python
CATEGORIES = [
    ...
    ("Minha Nova Categoria", f"{BASE_URL}/diretorio/minha-categoria.html"),
]
```
6.  Salve o arquivo e execute o scraper. O script criará automaticamente a aba "Minha Nova Categoria" (truncada para até 31 caracteres, limite máximo do Excel) no relatório.

## Estrutura da Planilha Excel (`lojaeletrica_infraestrutura.xlsx`)

*   **Aba "Todos":** Consolida os produtos de todas as categorias em uma única lista, contendo as colunas `Categoria`, `SKU`, `Produto`, `Preço (R$)`, `Preço (texto)`, `Preço Disponível`, `Link`, e `Imagem URL`.
*   **Aba "Resumo":** Relatório estatístico por categoria contendo:
    - *Produtos:* Contagem total de produtos cadastrados.
    - *Preços_Indisponíveis:* Quantidade de produtos que estão sem preço no site.
    - *Preço_Min, Preço_Médio, Preço_Max:* Valores calculados **excluindo** itens de preço R$ 0,00 para evitar distorção matemática.
*   **Abas de Categorias Individuais:** Cada categoria tem sua própria aba contendo seus respectivos produtos (colunas idênticas à aba "Todos", sem a coluna Categoria).

## Gotchas

*   **Bloqueio de Arquivos no Excel:** O pandas falhará com `PermissionError` se você tentar rodar o scraper com o arquivo `lojaeletrica_infraestrutura.xlsx` aberto no Microsoft Excel. Sempre feche a planilha antes de rodar.
*   **Nome das Abas (Limite do Excel):** O Excel limita o nome das abas a 31 caracteres. O scraper faz essa segurança automaticamente usando `cat[:31]` na geração das abas.
*   **Modo Headless:** Por padrão, o scraper abre o Chromium em modo invisível (headless) para máxima velocidade. Para fins de depuração visual, você pode alterar `headless=False` na chamada `playwright.chromium.launch()` dentro de `scripts/lojaeletrica_scraper.py`.
