# STATUS — CareerBrain Next

## Checkpoint da passada 03

**Estado atual certificado: 2/10 validadas.** A passada 03 tem implementação e
testes isolados aprovados; o aceite ainda depende de CI/PR e dos IDs OAuth públicos
aprovados para configuração real, antes de qualquer merge.

- 01 certificada e merged; fundação, contratos V1 e CI offline aprovados.
- 02: PostgreSQL 16, papéis mínimos/RLS, fila/outbox, migrações/checksums e índices.
  18 testes SQL e restore/ledger aprovados em worker isolado, com dados sintéticos.
- 03 autorizada e em execução: API base, OIDC e sessão revogável; 12 testes de
  autenticação aprovados com identidades sintéticas, sem login Google real.
- 04–10 não autorizadas nesta sequência.

Ver docs/database.md e docs/evidence-02.md. Nenhum banco produtivo, deploy público,
chamada de IA ou mudança de credenciais/permissões de integrações.
Auditoria geral de GitHub Apps permanece atividade de segurança independente.
