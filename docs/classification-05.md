# Classificação global assíncrona — execução 05

A passada 04 grava jobs por evento/revisão e outbox de publicação na mesma
transação de ingestão. O worker da 05 consome `queue.catalog_jobs` com papel
`cb_global_worker`, sem tenant nem dados privados. A classificação é de vaga
lógica e conteúdo versionado; eventos ativos da vaga apontam para o mesmo
resultado global. Nenhum score pessoal ou candidatura é calculado aqui.

## Correção aditiva de versões

A tabela legada `catalog.semantic_results` não tem modelo/prompt nem versão
numérica do conteúdo na chave. Ela permanece legível para compatibilidade e
não recebe resultados novos. A migração 006 acrescenta:

- Snapshot de versão/digest do conteúdo e versões de taxonomia, modelo e prompt
  em `queue.catalog_jobs` quando o job é adquirido. `task_version` continua a
  identificar o evento de ingestão, sem fingir que é versão de classificação.
- `catalog.classification_cache`, único por vaga, versão e digest de conteúdo,
  taxonomia, modelo e prompt; `catalog.event_classifications` liga eventos ativos
  ao cache. A view `catalog.current_classifications` só expõe a versão vigente
  de conteúdo e da política ativa.
- `queue.classification_outbox` publica READY ou UNCERTAIN na mesma transação
  que grava cache/projeções e conclui o job. `queue.catalog_outbox` continua a
  representar publicação, correção e remoção do produtor.

O operador pode agendar nova classificação por versão explícita. A política
ativa é única; uma troca de versões oculta imediatamente projeções antigas,
até a recomputação. Resultados atrasados não atualizam o estado vigente.

## Consumo e falha segura

Claim usa `FOR UPDATE SKIP LOCKED`, lease com dono e fencing token monotônico.
Lease vencido pode ser retomado; conclusão com token antigo falha. Três
attempts no máximo. Erro transitório, timeout ou saída inválida volta com
backoff limitado; esgotamento vira FAILED sem cache ou score fictício. Quota ou
credencial inválida do futuro provedor bloqueia o gate compartilhado do modelo
até ação externa explícita. O worker nunca seleciona modelo real ou usa chave
nesta execução.

Jobs com mais de 30 minutos são atendidos por idade antes dos recentes; dentro
do grupo recente, publicação mais nova vem primeiro. Lock consultivo por chave
de cache impede classificação simultânea da mesma versão. Conclusão confere
novamente lease, fencing, política, estado do evento e versão do conteúdo sob
locks de linha. Se o processo cai antes do commit, não ficam cache nem outbox
órfãos; após commit, a unicidade impede duplicação.

## Validação e adaptador

O adaptador `DeterministicClassifier` reconhece somente frases sintéticas de
saúde, manutenção, serviços e TI. Ele devolve atributos explícitos com trechos
exatos e offsets Unicode do campo original. Conteúdo sem suporte vira
`UNCERTAIN`, com atributo `unknown`, confiança zero e sem evidência. O resultado
passa pelo JSON Schema V1 e por verificação de envelope, campo, trecho, offset
e base. Texto de vaga é dado, mesmo quando contém instruções hostis.

A interface do adaptador exige timeout e usa exceções distintas para falha
transitória e gate de quota/credencial. Integração real, escolha de modelo,
benchmark, custos e tráfego pago permanecem sujeitos ao G-AI. O corpus fake
prova segurança e fluxo, não qualidade de inferência em vagas reais.
