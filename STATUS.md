# STATUS — CareerBrain Next

## Passada 07 em implementação

O branch `feat/passada-07-matching` contém a migração aditiva e os testes sintéticos
de matching privado e foi publicado em `origin` no commit
`cd0d26b8879701405934e9bc7f8cc34fb9d4b260`. A certificação, PR, checks, merge e
atualização para 7/10 estão bloqueados externamente: duas tentativas do dispatcher
PostgreSQL encontraram CI03 pronto, mas a descoberta foi roteada para outro
repositório e não iniciou a suíte; a autenticação do GitHub CLI também está inválida
para criar o PR. A decisão de produto para negativa foi aprovada e a extensão
compatível V2/V3 foi implementada localmente: somente requisito obrigatório e
atestado `NOT_MET` explícitos, ambos versionados e com trechos/offsets verificados,
emitem `REQUIREMENT_UNMET`; V1/V2 e ausência seguem `REQUIREMENT_UNKNOWN`. A
certificação continua bloqueada até o PostgreSQL no CI03; não houve fallback local
pesado. A passada 08 não foi iniciada.

## Checkpoint da passada 06

**6/10 certificadas e incorporadas à main.** A passada 06 foi integrada pelo
PR #9, após testes isolados e os checks obrigatórios.

- 01 certificada e merged; fundação, contratos V1 e CI offline aprovados.
- 02: PostgreSQL 16, papéis mínimos/RLS, fila/outbox, migrações/checksums e índices.
  18 testes SQL e restore/ledger aprovados em worker isolado, com dados sintéticos.
- 03: API base, OIDC e sessão revogável; 12 testes de autenticação aprovados
  com identidades sintéticas. Os dois IDs OAuth públicos aprovados foram testados
  com assinatura sintética fora do Git. Login Google real pertence à 10.
- 04: ingestão contratual autenticada com fixtures sintéticas; 12 testes de
  ingestão, 18 SQL, 12 identidade e restauração passaram no worker isolado.
  Direitos de fontes reais permanecem gate externo.
- Ajuste da 04 testado em worker: mesma evidência aprovada por produtores
  distintos resulta em duplicata, sem publicação ou trabalho novo.
- 05 certificada e merged: consumo com lease/fencing, cache global versionado
  e classificação determinística sintética, sem tráfego de IA real. O worker
  isolado aprovou 11 testes novos e as suítes anteriores; `contracts` e
  `repository-policy` passaram no PR #7.
- 06 certificada e merged: PDF transitório, handle opaco, limpeza, CAS de
  geração/epoch e perfil V2. CI03 aprovou 11 testes novos e regressões;
  `contracts` e `repository-policy` passaram no PR #9. A prova de ambiente
  produtivo continua externa.
- 07–10 não iniciadas nesta execução.

Ver docs/database.md, docs/evidence-02.md, docs/evidence-03.md,
docs/ingestion-04.md e docs/resume-06.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.
