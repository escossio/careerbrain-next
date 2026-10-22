# STATUS — CareerBrain Next

## Passada 07 em implementação

O branch `feat/passada-07-matching` contém a migração aditiva e os testes sintéticos
de matching privado. A certificação, PR, checks, merge e atualização para 7/10
dependem ainda do worker distribuído e dos gates remotos. A passada 08 não foi iniciada.

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
