# STATUS — CareerBrain Next

## Passada 07 — certificada e integrada

A execução 07 foi concluída pelo PR #11, merge squash
a5fab98cfa8cc28bfb9c0caeb0d4101d47461faa. A branch final
feat/passada-07-matching (979c59327b3814acf817ce43499eb19d535e6c6f)
inclui matching privado e corte temporal, versões e provas negativas
explícitas. REQUIREMENT_UNMET exige requisito obrigatório e atestado
NOT_MET com evidências versionadas; ausência permanece REQUIREMENT_UNKNOWN.
Contratos legados V1 permanecem compatíveis.

CI03 sem rede: PostgreSQL 18, restore/ledger, identidade 12,
ingestão 12, classificação 11, currículo 11 e matching 5: todos PASS.
GitHub Actions run 39849211014: 51 testes offline, checks contracts
e repository-policy SUCCESS no mesmo SHA. Nenhum artefato dos jobs,
credencial, dado real, deploy ou chamada paga. Main protegida.
08–10 não iniciadas nesta execução.

## Passada 08 — certificada e integrada

PR #13, merge squash `547bcf26d06f89b84f1500984ab72b11d94556f3`, incorporou
a migração aditiva 010: recomendações privadas paginadas, sync com snapshot e
watermark, ACK idempotente, candidaturas manuais com CAS e exclusão com receipt
opaco/capability e ledger. CI03 sem rede aprovou 18 SQL, restore/ledger, 12 de
identidade, 12 de ingestão, 11 de classificação, 11 de currículo e 8 de matching
(incluindo sync multi-dispositivo, CAS concorrente e exclusão). GitHub Actions
run 39858487393 aprovou `contracts` e `repository-policy` no SHA revisado.
Não houve dados reais, produção, deploy, credenciais ou tráfego pago. 09–10 não
foram iniciadas.

## Histórico das passadas 01–06

**8/10 certificadas e incorporadas à main.** A passada 06 foi integrada pelo
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
- 07 certificada e merged; PR #11 e cinco testes de matching aprovados no CI03.
- 08 certificada e merged; PR #13, CI03 e checks obrigatórios aprovados.
- 09–10 não iniciadas nesta execução.

Ver docs/database.md, docs/evidence-02.md, docs/evidence-03.md,
docs/ingestion-04.md e docs/resume-06.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.
