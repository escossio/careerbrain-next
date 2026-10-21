# STATUS — CareerBrain Next

## Checkpoint da passada 03

**Estado aplicado na main após checks verdes e merge deste PR: 3/10 validadas.**
Antes do merge, a passada 03 tem implementação, testes isolados e configuração
OAuth pública comprovados; CI no SHA final e merge protegido são condições de aceite.

- 01 certificada e merged; fundação, contratos V1 e CI offline aprovados.
- 02: PostgreSQL 16, papéis mínimos/RLS, fila/outbox, migrações/checksums e índices.
  18 testes SQL e restore/ledger aprovados em worker isolado, com dados sintéticos.
- 03: API base, OIDC e sessão revogável; 12 testes de autenticação aprovados
  com identidades sintéticas. Os dois IDs OAuth públicos aprovados foram testados
  com assinatura sintética fora do Git. Login Google real pertence à 10.
- 04–10 não autorizadas nesta sequência.

Ver docs/database.md, docs/evidence-02.md e docs/evidence-03.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.
