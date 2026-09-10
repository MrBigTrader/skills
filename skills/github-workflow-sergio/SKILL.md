---
name: github-workflow-sergio
description: "Use when working with GitHub. Enforces Sérgio's rules."
version: 1.0.0
---

# GitHub Workflow — Sérgio

Estas regras são obrigatórias em qualquer tarefa relacionada ao GitHub, a repositórios Git com remotos hospedados no GitHub ou a recursos administrados pelo GitHub.

## Ferramenta prioritária

- Priorize sempre o GitHub CLI (`gh`) já autenticado nesta máquina.
- Antes de usar o GitHub, verifique a autenticação existente com `gh auth status`.
- Para consultas, prefira `gh` aos demais meios de acesso.
- Não use navegador, scraping ou API pública quando o `gh` autenticado puder realizar a tarefa.
- Use `gh api` somente quando o comando de alto nível apropriado não existir e a operação puder ser realizada usando a autenticação já disponível.
- Nunca crie, substitua, renove, reconfigure ou sobrescreva credenciais, tokens, chaves ou outros mecanismos de autenticação do GitHub.
- Se a autenticação existente não funcionar, interrompa a operação dependente dela e informe o problema ao usuário, sem tentar criar ou substituir credenciais.

## Operações remotas autônomas de leitura

É permitido executar autonomamente apenas operações remotas de leitura, incluindo:

- Consultar repositórios e seus metadados.
- Ler diretórios e arquivos.
- Listar e inspecionar branches e tags.
- Consultar commits e histórico.
- Ler issues, comentários, labels, assignees e milestones.
- Ler Pull Requests, comentários, revisões, diffs e histórico.
- Consultar checks, workflows, execuções de CI e seus logs.
- Consultar releases, configurações e demais metadados, desde que a operação não altere o estado remoto.
- Verificar autenticação e permissões existentes sem modificá-las.

Operações de leitura não exigem confirmação prévia.

## Operações locais autônomas

É permitido executar autonomamente operações locais necessárias ao trabalho, desde que nenhuma alteração seja enviada ao GitHub ou a outro remoto. Isso inclui:

- Clonar repositórios para um workspace autorizado.
- Criar, trocar e modificar branches locais.
- Criar, editar, mover ou remover arquivos dentro do workspace autorizado, respeitando as regras de proteção contra perda de trabalho local.
- Instalar somente dependências declaradas pelo projeto e somente dentro do ambiente ou workspace do próprio projeto.
- Executar testes, lint, análise estática, formatação e builds.
- Gerar e inspecionar diffs.
- Fazer staging de alterações locais.
- Criar commits locais.
- Consultar o estado e o histórico do repositório local.

Instalações globais de dependências, alterações no sistema operacional ou mudanças em configurações globais exigem confirmação explícita prévia.

Essas permissões locais não autorizam:

- Enviar commits, branches ou tags para qualquer remoto.
- Alterar recursos ou configurações no GitHub.
- Executar comandos locais que tenham efeitos remotos indiretos.
- Publicar pacotes, artefatos, imagens, releases ou deployments.
- Executar scripts, testes, hooks ou ferramentas que façam alterações remotas sem confirmação explícita prévia.

Antes de executar uma ferramenta ou script cujo efeito remoto não esteja claro, trate a operação como potencialmente remota e solicite confirmação explícita.

## Proteção contra perda de trabalho local

- Verifique `git status` antes de qualquer operação local que possa remover, sobrescrever ou tornar irrecuperáveis alterações ou arquivos.
- Não execute autonomamente `git clean -fd`, `git reset --hard`, exclusões recursivas ou operações equivalentes quando elas puderem remover alterações locais ou arquivos não versionados.
- Considere também o risco para arquivos ignorados, alterações em staging, commits locais não publicados e trabalhos em outras árvores de trabalho quando aplicável.
- Havendo qualquer risco de perda, interrompa a operação, descreva os recursos locais afetados sem expor segredos e solicite confirmação explícita.
- Uma autorização genérica para editar, testar, compilar ou limpar o projeto não constitui autorização para descartar trabalho local.

## Confirmação obrigatória para alterações remotas

Solicite confirmação explícita imediatamente antes de qualquer ação que altere o estado remoto.

A solicitação deve identificar claramente:

- A ação proposta.
- O repositório e o recurso afetados.
- A branch, issue, Pull Request, release, configuração ou outro alvo relevante.
- O efeito esperado.
- O comando, ou uma descrição precisa dos comandos, que serão executados.

A confirmação vale somente para a ação e para o alvo apresentados. Não reutilize uma confirmação para ações adicionais ou diferentes.

Exigem confirmação explícita específica, entre outras:

- Qualquer `push` de commits, branches ou tags.
- Qualquer merge de Pull Request ou branch.
- Criação, edição, rotulagem, atribuição, transferência, bloqueio, desbloqueio, reabertura ou fechamento de issues.
- Criação, edição, revisão formal, aprovação, solicitação de alterações, conversão, reabertura ou fechamento de Pull Requests.
- Publicação de comentários, respostas ou reações em issues, Pull Requests, commits ou discussões.
- Criação, edição, publicação ou remoção de releases.
- Criação, alteração, renomeação, proteção, desproteção ou exclusão de branches remotas.
- Criação, alteração ou remoção de tags remotas.
- Alterações em configurações de repositórios, organizações, Actions, workflows, ambientes, secrets, variables, webhooks, integrações, permissões ou regras de proteção.
- Alterações em colaboradores, equipes, acessos ou papéis.
- Execução ou reexecução de workflows quando isso criar ou alterar estado remoto.
- Publicação de pacotes, artefatos, deployments ou outros recursos remotos.

Uma solicitação geral para trabalhar em uma tarefa não constitui, por si só, autorização para executar alterações remotas. Obtenha confirmação no momento em que a ação remota estiver pronta para ser realizada.

Depois de qualquer alteração remota autorizada, verifique o resultado com uma operação de leitura usando `gh` antes de informar que a ação foi concluída.

## Operações proibidas e exclusões

- Nunca execute force-push, incluindo `git push --force`, `git push -f`, `git push --force-with-lease` ou qualquer operação equivalente.
- Nunca exclua branches remotas ou repositórios sem confirmação específica, separada e inequívoca para o recurso a ser removido.
- A confirmação para excluir deve identificar pelo nome:
  - O repositório exato, no formato `owner/repository`; ou
  - A branch remota exata e o respectivo repositório.
- Uma confirmação para push, merge, limpeza, manutenção ou outra operação não autoriza exclusão.
- Nunca crie ou substitua credenciais GitHub.

## Proteção de segredos

- Nunca exiba, registre, copie para logs, inclua em respostas, commite ou envie:
  - Tokens e personal access tokens.
  - Conteúdo de arquivos `.env`.
  - Chaves privadas.
  - Senhas e credenciais.
  - Cookies e dados de sessão.
  - Arquivos de autenticação.
  - Secrets, certificados privados ou materiais equivalentes.
- Nunca adicione esses dados ao staging, a commits, a patches destinados a terceiros, a issues, a Pull Requests, a comentários, a releases ou a qualquer recurso remoto.
- Não revele o conteúdo integral de tokens ou credenciais retornados por comandos. Quando necessário, informe apenas que uma credencial existe, está ausente ou falhou, mantendo seu valor oculto.
- Antes de criar um commit local, inspecione as alterações preparadas para detectar segredos ou arquivos sensíveis.
- Se houver indício de segredo nas alterações:
  - Interrompa o commit ou envio.
  - Não reproduza o valor detectado.
  - Informe apenas o tipo de risco e o arquivo afetado.
  - Aguarde instruções do usuário.
- Não altere, remova, rotacione ou substitua um segredo sem instrução e confirmação explícitas.
- O fato de um segredo já existir no histórico não autoriza sua exibição, reutilização ou novo envio.

## Hierarquia operacional

Para tarefas no GitHub:

1. Use `gh` autenticado para consultas remotas.
2. Execute autonomamente apenas leituras remotas e operações locais permitidas.
3. Verifique `git status` antes de operações potencialmente destrutivas e proteja todo trabalho local.
4. Prepare e verifique localmente todas as mudanças possíveis.
5. Pare antes da primeira alteração remota.
6. Apresente a ação, o alvo, o efeito e os comandos propostos.
7. Aguarde confirmação explícita.
8. Execute somente o que foi especificamente autorizado.
9. Verifique o estado remoto resultante com `gh`.
